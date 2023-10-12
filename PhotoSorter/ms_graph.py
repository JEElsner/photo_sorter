import requests
from collections import namedtuple
from typing import List, Dict
from pprint import pprint
import time
import queue
import threading
from pathlib import Path
import logging as _logging
from . import main_log

logging = main_log.getChild(__name__)

BATCH_REQUEST_MAX = 20
"""Maximum number of requests per batch allowed."""

EMPTY_LIMIT = 100
"""The number of empty pages to allow when getting the children of a folder
before quitting.

Sometimes the Graph API returns empty pages of results for the children of a
folder and sometimes after several empty pages, a non-empty page will be
returned. This parameter balances how many empty pages will be checked before
assuming that all remaining pages are empty and terminating the search for more
children.

It's hard to determine what a good number is for this parameter, but it seems
that 100 is conservative, in that this checks many empty pages before stopping.
"""


class Graph:
    def __init__(self, client_id, tenant_id, scopes):
        self.total_requests_made = 0

        if Path("./token.txt").exists():
            with open("./token.txt") as f:
                self.__token = f.read()
        else:
            json = self._device_code_auth(client_id, tenant_id, scopes)
            self.__token = json["access_token"]

            with open("./token.txt", mode="w") as f:
                f.write(self.__token)

        logging.info("Graph initialized")

    def request_wrapper(self, method: str, *args, **kwargs):
        # Modify the headers to include authentication
        headers = kwargs.get("headers", dict())
        headers.update({"Authorization": f"Bearer {self.__token}"})
        kwargs["headers"] = headers

        r = requests.request(method, *args, **kwargs)

        logging.debug(f"{method}\t{r.url}\t{kwargs.get('json', '')!s:.100}")

        self.total_requests_made += 1
        data = r.json()

        # Deal with any common errors
        if r.status_code == 400:
            if data["error"]["message"] == "Tenant does not have a SPO license.":
                raise RuntimeError(
                    "Incorrect Microsoft AD settings. Must set supported account types to consumer"
                )
        elif r.status_code == 401:
            if data["error"]["code"] == "InvalidAuthenticationToken":
                raise RuntimeError("Bad authentication token", data["error"]["message"])

        return r

    def _device_code_auth(
        self, client_id: str, tenant_id: str, scopes: List[str]
    ) -> Dict | None:
        # Concatenate the scopes into one string, the format necessary for the POST request
        scopes = " ".join(scopes)

        url = f"https://login.microsoftonline.com/consumers/oauth2/v2.0/devicecode"
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        data = f"client_id={client_id}&scope={scopes}"

        r = requests.post(url, headers=headers, data=data)
        if r.status_code != 200:
            raise RuntimeError(
                "Failed to initiate device code flow",
                r.status_code,
                r.json()["error_description"],
            )

        # At this point, the initial request was successful, so we can go ahead and
        # authenticate it

        device_code = r.json()["device_code"]
        wait_time = r.json()["interval"]
        print(r.json()["message"])

        # Wait for the user to authenticate
        while True:
            url = f"https://login.microsoftonline.com/consumers/oauth2/v2.0/token"
            headers = {"Content-Type": "application/x-www-form-urlencoded"}
            data = f"grant_type=urn:ietf:params:oauth:grant-type:device_code&client_id={client_id}&device_code={device_code}"

            r = requests.post(url, headers=headers, data=data)

            if r.status_code == 400 and r.json()["error"] == "authorization_pending":
                # User has yet to authenticate
                time.sleep(wait_time)
                continue
            elif r.status_code == 400 and r.json()["error"] == "invalid_grant":
                # device_code was already used
                print("Current device code already used. Please try again.")
                return None
            elif r.status_code == 400 and r.json()["error"] == "expired_token":
                # User failed to authenticate in time
                print("Authorization timed out")
                return None
            elif r.status_code == 400 and r.json()["error"] == "authorization_declined":
                # User refused authentication
                print("Authorization declined")
                return None
            elif r.status_code != 200:
                # Something weird happened
                raise RuntimeError(
                    "Failed to complete authentication",
                    r.status_code,
                    r.json()["error_description"],
                )

            # Authorization succeeded, so return the authentication token
            return r.json()

    def get_file_id(self, file_path, from_folder: str = None) -> str | None:
        header = {"Authorization": f"Bearer {self.__token}"}
        if from_folder is None:
            url = f"https://graph.microsoft.com/v1.0/me/drive/root:/{file_path}?$select=id"
        else:
            url = f"https://graph.microsoft.com/v1.0/me/drive/items/{from_folder}/children/{file_path}?$select=id"

        r = self.request_wrapper("GET", url, headers=header)
        if r.status_code == 404 and (
            r.json()["error"]["code"] == "itemNotFound"
            or (
                r.json()["error"]["code"] == "UnknownError"
                and "No HTTP resource was found" in r.json()["error"]["message"]
            )
        ):
            return None
        if r.status_code != 200:
            raise RuntimeError(
                "Failed to get file id", r.status_code, r.json()["error"]
            )

        return r.json()["id"]

    def get_file_children(
        self, file_id: str, select: List[str] | None = None, top: int | None = None
    ) -> iter:
        """Get the child items of a folder.

        The Microsoft Graph API returns the children in pages of results. The
        ``top`` argument specifies the maximum number of results per page.

        Args:
            file_id: The id of the folder of which to select the children
            select: The list of attributes to select about the children
            top: The maximum number of results per page

        Yields:
            The JSON representation of one child at a time, with the selected
            attributes.

        Raises:
            RuntimeError: If the graph fails to get the children or cannot get
                more children (even though there should be more).
        """

        header = {"Authorization": f"Bearer {self.__token}"}
        url = f"https://graph.microsoft.com/v1.0/me/drive/items/{file_id}/children"

        if select:
            select = ",".join(select)

        params = dict()

        if select:
            params["$select"] = select

        if top:
            params["$top"] = top

        r = self.request_wrapper("GET", url, headers=header, params=params)
        if r.status_code != 200:
            raise RuntimeError(
                "Failed to get file children", r.status_code, r.json()["error"]
            )

        json = r.json()
        yield from iter(json["value"])

        empty_results = 0

        while json.get("@odata.nextLink") is not None:
            # For whatever reason, sometimes OneDrive keeps giving next links,
            # but all of the values are empty. Short-circut and stop after
            # several empty pages of results
            if empty_results >= EMPTY_LIMIT:
                logging.warn("Too many pages of empty results of children. Stopping.")
                break

            r = self.request_wrapper("GET", json["@odata.nextLink"], headers=header)
            if r.status_code != 200:
                raise RuntimeError(
                    "Failed to get more child items", r.status_code, r.json()["error"]
                )

            json = r.json()

            if len(json["value"]) == 0:
                empty_results += 1
                logging.warn(
                    f"Empty children result page encountered, count: {empty_results}"
                )

            yield from iter(json["value"])

    def get_file_info(self, file_id, select=None):
        header = {"Authorization": f"Bearer {self.__token}"}
        url = f"https://graph.microsoft.com/v1.0/me/drive/items/{file_id}"

        if select:
            url += "?$select=" + ",".join(select)

        r = self.request_wrapper("GET", url, headers=header)
        if r.status_code != 200:
            raise RuntimeError(
                "Failed to get file info", r.status_code, r.json()["error"]
            )

        return r.json()["value"]

    def move_file(self, file_id: str, new_location_id: str):
        header = {"Authorization": f"Bearer {self.__token}"}
        url = f"https://graph.microsoft.com/v1.0/me/drive/items/{file_id}"
        content = {
            "parentReference": {"id": new_location_id},
            "@microsoft.graph.conflictBehavior": "fail",
        }

        logging.debug(f"Moving file\t{file_id}")

        r = self.request_wrapper("PATCH", url, headers=header, json=content)

        if r.status_code == 409 and r.json()["error"]["code"] == "nameAlreadyExists":
            raise RuntimeError(
                f"File {file_id} not moved: name already exists in {new_location_id}",
                file_id,
                new_location_id,
            )
        elif r.status_code != 200:
            raise RuntimeError(f"Failed to move file {file_id}", r.json()["error"])

    def create_directory(self, parent_id: str, name: str) -> str:
        header = {
            "Authorization": f"Bearer {self.__token}",
            # "Content-Type": "application/json",
        }
        url = f"https://graph.microsoft.com/v1.0/me/drive/items/{parent_id}/children?$select=id"
        body = {"name": name, "folder": {}}

        r = self.request_wrapper("POST", url, headers=header, json=body)
        if r.status_code not in [200, 201]:
            raise RuntimeError(
                f"Failed to create new folder {name}", r.status_code, r.json()["error"]
            )

        return r.json()["id"]

    def ensure_path(self, base_id: str, subdirs: List[str]) -> str:
        requests = list()

        # Base case for recursion, just return the folder when there are no
        # more folders to verify/create
        if len(subdirs) < 1:
            return base_id

        # Create the requests sequentially
        path_so_far = ""
        for i, folder in enumerate(subdirs[:BATCH_REQUEST_MAX]):
            requests.append(
                {
                    "id": f"{i}",
                    "method": "POST",
                    "url": f"/me/drive/items/{base_id}:{path_so_far}:/children?$select=id",
                    "headers": {"Content-Type": "application/json"},
                    "body": {"name": folder, "folder": dict()},
                }
            )

            if i > 0:
                requests[-1].update({"dependsOn": [f"{i-1}"]})

            path_so_far = f"{path_so_far}/{folder}"

        r = self.request_wrapper(
            "POST",
            url="https://graph.microsoft.com/v1.0/$batch",
            json={"requests": requests},
        )

        # Look through the responses for the last one
        for resp in r.json()["responses"]:
            # Ignore all but the last response
            if resp["id"] != f"{i}":
                continue

            # Deal with failures... kind of
            if resp["status"] not in [200, 201]:
                raise RuntimeError(f"Failed to fully ensure path to {subdirs[-1]}")

            # Repeat if more folders need to be created
            return self.ensure_path(resp["body"]["id"], subdirs[BATCH_REQUEST_MAX:])


class BatchMoveQueue(threading.Thread):
    MAX_ITEMS = BATCH_REQUEST_MAX
    TIMEOUT = 1

    MoveOrder = namedtuple("MoveOrder", ["file_id", "new_parent"])

    def __init__(self, graph: Graph, *args, **kwargs):
        threading.Thread.__init__(self, *args, **kwargs)

        self.graph = graph

        self._q = queue.Queue()
        self.__stop = threading.Event()

    def put(self, file_id: str, new_parent: str):
        logging.debug(f"Put item in queue\t{file_id}")
        if not self.__stop.is_set():
            self._q.put(BatchMoveQueue.MoveOrder(file_id, new_parent))

    def done_adding(self):
        logging.debug(f"Queue stop condition set")
        self.__stop.set()

    def run(self):
        logging.debug("BatchMoveQueue started")
        while not self.__stop.is_set():
            logging.debug("Starting new batch")

            requests = list()
            counter = 0
            for i in range(BatchMoveQueue.MAX_ITEMS):
                while not self.__stop.is_set():
                    try:
                        file_id, new_parent = self._q.get(
                            timeout=BatchMoveQueue.TIMEOUT
                        )
                        break
                    except queue.Empty:
                        pass
                else:
                    break

                logging.debug(f"Adding item to batch\t{file_id}")

                requests.append(
                    {
                        "id": f"{counter}",
                        "method": "PATCH",
                        "url": f"/me/drive/items/{file_id}",
                        "headers": {"Content-Type": "application/json"},
                        "body": {
                            "parentReference": {"id": new_parent},
                            "@microsoft.graph.conflictBehavior": "fail",
                        },
                    }
                )
                counter += 1

            logging.info(
                f"Moving batch of {counter} images now. Approximately {self._q.qsize()} more images in queue."
            )

            r = self.graph.request_wrapper(
                "POST",
                url="https://graph.microsoft.com/v1.0/$batch",
                json={"requests": requests},
            )

            if r.status_code != 200:
                err = r.json()["error"]
                message = err["message"]
                logging.warn(f"Error processing batch: {message}")

            if not r.json().get("responses") and counter == 0:
                continue

            for resp in r.json()["responses"]:
                if resp["status"] not in [200, 201]:
                    body = resp["body"]
                    err = body["error"]
                    error_code = err["code"]
                    message = err["message"]
                    logging.warn(f"Failed to move file: {message}")

                try:
                    self._q.task_done()
                except ValueError:
                    pass

        logging.debug("Batch processing stopped")


if __name__ == "__main__":
    import json

    with open("./auth.json", mode="r") as f:
        auth_info = json.load(f)
        graph = Graph(auth_info["clientId"], auth_info["tenantId"], auth_info["scopes"])

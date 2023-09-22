import requests
from collections import namedtuple
from typing import List, Dict
from pprint import pprint
import time
import queue
import threading
from pathlib import Path
import logging as _logging

logging = _logging.getLogger(__name__)

BATCH_REQUEST_MAX = 20


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

    def get_file_children(self, file_id, select=None, top=None) -> iter:
        header = {"Authorization": f"Bearer {self.__token}"}
        url = f"https://graph.microsoft.com/v1.0/me/drive/items/{file_id}/children"

        if select:
            select = ",".join(select)

        params = {"$select": select, "$top": top}

        r = self.request_wrapper("GET", url, headers=header, params=params)
        if r.status_code != 200:
            raise RuntimeError(
                "Failed to get file children", r.status_code, r.json()["error"]
            )

        json = r.json()
        yield from iter(json["value"])

        while json.get("@odata.nextLink") is not None:
            r = self.request_wrapper("GET", json["@odata.nextLink"], headers=header)
            if r.status_code != 200:
                raise RuntimeError(
                    "Failed to get more child items", r.status_code, r.json()["error"]
                )

            json = r.json()
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
        self.graph = graph

        self._q = queue.Queue()
        self._stop = threading.Event()

        super().__init__(*args, **kwargs)

    def put(self, file_id: str, new_parent: str):
        logging.debug(f"Put item in queue\t{file_id}")
        if not self._stop.is_set():
            self._q.put(BatchMoveQueue.MoveOrder(file_id, new_parent))

    def done_adding(self):
        logging.debug(f"Queue stop condition set")
        self._stop.set()

    def join(self, timeout: float | None = None):
        logging.debug(f"BatchMoveQueue requested to join")

        self._q.join()
        logging.debug(f"Queue joined. Waiting for BatchMoveQueue thread to join.")

        super().join(timeout)
        logging.debug("BatchMoveQueue thread joined")

    def run(self):
        logging.debug("BatchMoveQueue started")
        while not self._stop.is_set() and not self._q.all_tasks_done:
            logging.debug("Starting new batch")

            requests = list()
            counter = 0
            for i in range(BatchMoveQueue.MAX_ITEMS):
                while not self._stop.is_set() and not self._q.all_tasks_done:
                    try:
                        file_id, new_parent = self._q.get(
                            timeout=BatchMoveQueue.TIMEOUT
                        )
                        counter += 1
                    except queue.Empty:
                        pass

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

            logging.debug("Processing batch of {counter} items now")

            r = self.request_wrapper(
                "POST",
                url="https://graph.microsoft.com/v1.0/$batch",
                json={"requests": requests},
            )

            logging.debug(f"Batch Processed {counter} items processed")

            for i in range(counter):
                self._q.task_done()


if __name__ == "__main__":
    import json

    with open("./auth.json", mode="r") as f:
        auth_info = json.load(f)
        graph = Graph(auth_info["clientId"], auth_info["tenantId"], auth_info["scopes"])

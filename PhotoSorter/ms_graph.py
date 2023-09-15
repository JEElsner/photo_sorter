import requests
from typing import List, Dict
from pprint import pprint
import time
import queue
import threading
from pathlib import Path


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
        kwargs.update({"Authentication": f"Bearer {self.__token}"})

        r = requests.request(method, *args, **kwargs)
        self.total_requests_made += 1
        data = r.json()

        if r.status_code == 400:
            if data["error"]["message"] == "Tenant does not have a SPO license.":
                pass

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

        r = requests.get(url, headers=header)
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

        r = requests.get(url, headers=header, params=params)
        if r.status_code != 200:
            raise RuntimeError(
                "Failed to get file children", r.status_code, r.json()["error"]
            )

        json = r.json()
        yield from iter(json["value"])

        while json.get("@odata.nextLink") is not None:
            r = requests.get(json["@odata.nextLink"], headers=header)
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

        r = requests.get(url, headers=header)
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

        r = requests.patch(url, headers=header, json=content)

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

        r = requests.post(url, headers=header, json=body)
        if r.status_code not in [200, 201]:
            raise RuntimeError(
                f"Failed to create new folder {name}", r.status_code, r.json()["error"]
            )

        return r.json()["id"]

    def ensure_path(self, base_id: str, subdirs: List[str]) -> str:
        file = self.get_file_id("/".join(subdirs), from_folder=base_id)
        if file:
            return file

        path = ""
        curr_parent = base_id
        for subdir in subdirs:
            curr_parent = self.create_directory(curr_parent, subdir)

        return curr_parent


class BatchMoveQueue(threading.Thread):
    MAX_ITEMS = 20
    TIMEOUT = 1

    def __init__(self, graph: Graph):
        self.graph = graph

        self._q = queue.Queue
        self._stop = threading.Event()

    def put(self, item):
        if not self._stop.is_set():
            self.q.put(item)

    def done_adding(self):
        self._stop.set()

    def run(self):
        while not self._stop.is_set():
            requests = list()
            for i in range(BatchMoveQueue.MAX_ITEMS):
                while not self._stop.is_set():
                    try:
                        item = self._q.get(timeout=BatchMoveQueue.TIMEOUT)
                    except queue.Empty:
                        pass


if __name__ == "__main__":
    import json

    with open("./auth.json", mode="r") as f:
        auth_info = json.load(f)
        graph = Graph(auth_info["clientId"], auth_info["tenantId"], auth_info["scopes"])

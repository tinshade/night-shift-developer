import requests
import argparse
from random import randint

parser = argparse.ArgumentParser(description="Trigger application errors in the API server.")
parser.add_argument(
    "--mode",
    choices=("delete", "post"),
    required=False,
    help="The error scenario to trigger. Defaults to a random scenario.",
)




def force_error_with_delete():
    missing_user_id = randint(1000000, 9999999)
    url = f"http://fastapi:8000/users/{missing_user_id}"
    response = requests.delete(url, timeout=10)
    print(f"DELETE request to {url} returned status code {response.status_code} and response: {response.json()}")
    if response.status_code != 404:
        raise RuntimeError(f"Expected the missing-user error, received HTTP {response.status_code}.")
    
def force_error_with_post():
    """Exercise the create route with a valid payload, then force a logged delete error."""
    create_url = "http://fastapi:8000/users/create"
    payload = {
        "first_name": "Night Shift",
        "last_name": "Doe",
        "email": f"night-shift-{randint(100000, 999999)}@example.com",
    }
    response = requests.post(create_url, json=payload, timeout=10)
    print(f"POST request to {create_url} returned status code {response.status_code} and response: {response.json()}")
    response.raise_for_status()

    delete_url = f"http://fastapi:8000/users/{randint(1000000, 9999999)}"
    error_response = requests.delete(delete_url, timeout=10)
    print(f"DELETE request to {delete_url} returned status code {error_response.status_code} and response: {error_response.json()}")
    if error_response.status_code != 404:
        raise RuntimeError(f"Expected the missing-user error, received HTTP {error_response.status_code}.")
    


def main():
    args = parser.parse_args()
    mode = args.mode
    
    if not mode:
        modes = {
            1: force_error_with_delete,
            2: force_error_with_post
        }
        
        random_mode = randint(1, 2)
        modes[random_mode]()
        return
        

    if mode == "delete":
        force_error_with_delete()
    elif mode == "post":
        force_error_with_post()


if __name__ == "__main__":
    main()
import requests
import argparse
from random import randint

parser = argparse.ArgumentParser(description="Force an error in the API server.")
parser.add_argument("--mode", type=str, required=False, help="The type of API endpoint to call.")




def force_error_with_get():
    url = "http://fastapi:8000/users/9999"  # Assuming this ID does not exist
    response = requests.get(url)
    print(f"GET request to {url} returned status code {response.status_code} and response: {response.json()}")
    
def force_error_with_post():
    url = "http://fastapi:8000/users/create"
    payload = {
        "first_name": None,  # This will cause an error when trying to call .title() on it
        "last_name": "Doe",
        "email": "johndoe@example.com"
    }
    response = requests.post(url, json=payload)
    print(f"POST request to {url} returned status code {response.status_code} and response: {response.json()}")
    


def main():
    args = parser.parse_args()
    mode = args.mode.lower() if args.mode else None
    
    if not mode:
        modes = {
            1: force_error_with_get,
            2: force_error_with_post
        }
        
        random_mode = randint(1, 2)
        mode = modes[random_mode]()
        

    if mode == "get":
        force_error_with_get()
    elif mode == "post":
        force_error_with_post()
    else:
        print("Invalid mode. Use 'get' or 'post'.")


if __name__ == "__main__":
    main()
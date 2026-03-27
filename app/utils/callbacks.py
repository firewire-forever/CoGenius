import requests
from flask import current_app, jsonify
import json

def send_callback(callback_url: str, task_id: str, status: str, data: dict = None, error: str = None):
    """
    Sends a callback to the specified URL with the task's result.

    Args:
        callback_url: The URL to send the callback to.
        task_id: The unique ID of the task.
        status: The final status of the task ('SUCCESS' or 'FAILED').
        data: A dictionary containing the successful result data (e.g., path to artifacts).
        error: A string describing the error if the task failed.
    """
    payload = {
        "task_id": task_id,
        "status": status,
    }
    if status == 'SUCCESS':
        payload['data'] = data
    else:
        payload['error'] = error

    try:
        headers = {'Content-Type': 'application/json'}
        response = requests.post(callback_url, data=json.dumps(payload), headers=headers, timeout=30)
        response.raise_for_status()  # Raise an exception for bad status codes (4xx or 5xx)
        current_app.logger.info(f"Successfully sent callback for task {task_id} to {callback_url}. Status: {status}")
    except requests.exceptions.RequestException as e:
        current_app.logger.error(f"Failed to send callback for task {task_id} to {callback_url}. Error: {e}") 
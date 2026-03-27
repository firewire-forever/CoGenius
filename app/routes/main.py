from flask import Blueprint, jsonify

main_bp = Blueprint('main', __name__)

@main_bp.route('/')
def index():
    """
    API Welcome Page
    ---
    tags:
      - Home
    summary: API Welcome Page
    description: Returns API welcome message
    responses:
      200:
        description: Success
        schema:
          type: object
          properties:
            message:
              type: string
    """
    return jsonify({'message': '欢迎使用 Flask API!'})

@main_bp.route('/health')
def health():
    """
    Health Check
    ---
    tags:
      - System
    summary: Health Check
    description: Check if the API service is running properly
    responses:
      200:
        description: Service is healthy
        schema:
          type: object
          properties:
            status:
              type: string
    """
    return jsonify({'status': 'healthy'})

@main_bp.route('/users', methods=['GET'])
def get_users():
    """
    Get All Users
    ---
    tags:
      - Users
    summary: Get All Users
    description: Returns a list of all users in the system
    responses:
      200:
        description: Successfully retrieved user list
        schema:
          type: object
          properties:
            users:
              type: array
              items:
                type: object
    """
    # Logic to retrieve user list
    return jsonify({'users': []}) 

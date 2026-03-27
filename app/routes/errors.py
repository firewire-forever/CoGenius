from flask import jsonify

def register_error_handlers(app):
    @app.errorhandler(400)
    def bad_request(e):
        return jsonify({'error': 'Bad request parameters'}), 400
        
    @app.errorhandler(404)
    def not_found(e):
        return jsonify({'error': 'Resource not found'}), 404
        
    @app.errorhandler(500)
    def internal_server_error(e):
        return jsonify({'error': 'Internal server error'}), 500 

import os
from dotenv import load_dotenv
from flask import Flask
from flask_cors import CORS
from flasgger import Swagger
from app.utils.logger import setup_logger

swagger = Swagger()

def create_app(config_name='development'):
    app = Flask(__name__)
    
    # Load configuration
    from app.config import config
    app.config.from_object(config[config_name])
    
    # Celery Configuration
    # Reads from environment variables, with fallbacks for local development
    app.config.from_mapping(
        CELERY=dict(
            broker_url=os.environ.get('CELERY_BROKER_URL', 'redis://localhost:6379/0'),
            result_backend=os.environ.get('CELERY_RESULT_BACKEND', 'redis://localhost:6379/0'),
            task_ignore_result=True,
            broker_connection_retry_on_startup=True, # Explicitly set to handle the warning
        ),
    )
    
    # Set up logging system
    setup_logger(app)
    
    # Swagger configuration
    app.config['SWAGGER'] = {
        'title': 'CRCG API',
        'description': 'CRCG - Target Range Management System API Documentation',
        'version': '1.0.0',
        'uiversion': 3,
        'doc_dir': './docs/swagger/',
        'specs_route': '/api/docs/',
        'termsOfService': '',
        'schemes': ['http', 'https'],
    }
    
    # Initialize extensions
    CORS(app)
    swagger.init_app(app)
    
    # Initialize singleton services that need app context
    from app.services.openstack_service import get_openstack_service
    with app.app_context():
        openstack_service = get_openstack_service()
        openstack_service.initialize_data()

    # Create and register Celery
    from app.celery_factory import create_celery
    create_celery(app)

    # Register blueprints
    from app.routes.main import main_bp
    from app.routes.target_range import target_range_bp
    
    app.register_blueprint(main_bp, url_prefix='/api/v1')
    app.register_blueprint(target_range_bp, url_prefix='/api/v1/target-range')
    
    # Register error handlers
    from app.routes import errors
    errors.register_error_handlers(app)
    # Test log writing
    app.logger.info("Flask startup log test")
    return app

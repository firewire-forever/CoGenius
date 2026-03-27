import pytest
from app import create_app, db

@pytest.fixture(scope='module')
def test_app():
    """Create and configure a new app instance for each test module."""
    app = create_app(config_name='testing')
    with app.app_context():
        db.create_all()
        yield app
        db.drop_all()

@pytest.fixture(scope='module')
def test_client(test_app):
    """A test client for the app."""
    return test_app.test_client() 
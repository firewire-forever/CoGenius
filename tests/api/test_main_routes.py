import json

def test_index_route(test_client):
    """
    GIVEN a Flask application configured for testing
    WHEN the '/' route is requested (GET)
    THEN check that the response is valid
    """
    response = test_client.get('/api/v1/')
    assert response.status_code == 200
    data = json.loads(response.data)
    assert data['message'] == '欢迎使用 Flask API!'

def test_health_check_route(test_client):
    """
    GIVEN a Flask application configured for testing
    WHEN the '/health' route is requested (GET)
    THEN check that the response is valid
    """
    response = test_client.get('/api/v1/health')
    assert response.status_code == 200
    data = json.loads(response.data)
    assert data['status'] == 'healthy' 
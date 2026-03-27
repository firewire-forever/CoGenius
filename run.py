from app import create_app
from app.cli import register_commands

app = create_app()
register_commands(app)

if __name__ == '__main__':
    app.run(debug=True) 
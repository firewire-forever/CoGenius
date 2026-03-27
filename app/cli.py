import click
from flask.cli import with_appcontext
import os
import json

def register_commands(app):
    """Register custom command-line commands."""
    
    @app.cli.command("greet")
    @click.argument("name")
    def greet_command(name):
        """A simple command to greet a user."""
        print(f"Hello, {name}!")

    # Since the Case model is removed, the 'import-cases' command is no longer valid.
    # It has been removed to align with the new stateless architecture.
    # If a similar functionality is needed in the future, it should be implemented
    # without direct database interaction, for example, by calling an external API. 
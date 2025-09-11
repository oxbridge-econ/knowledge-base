import os
from controllers.file import FileHandler # To be use

SERVICE = "file"

class FileService():
    def __init__(self, user_id: str = None, task: str = None, content: bytes = None, filename: str = None):
        self.task = task
        self.user_id = user_id
        if task:
            self.task = task
        path = os.path.join(f"/{user_id}", filename)
        with open(path, "wb") as f:
            f.write(content)
    
    def load(self):
        pass

    def get(self):
        pass

    def delete(self):
        pass
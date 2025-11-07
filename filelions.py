import json
import base64
import re
import subprocess

import requests

from bs4 import BeautifulSoup
from bs4.element import Tag

    
class Response: 
    def __init__(self, data: dict | str):
        self.data = data
    
    def __str__(self): 
        return json.dumps(self.data, indent=2)

    def text(self): 
        return str(self.data)

    def get(self, key: str): 
        if isinstance(self.data, dict): 
            return self.data.get(key)
    
class Request: 
    @staticmethod
    def extract(res: requests.Response) -> Response: 
        try: 
            res_json = res.json()
            return Response(res_json)
        except: 
            return Response(res.text)
    
    @staticmethod
    def get(url: str, *args, **kwargs) -> Response: 
        res = requests.get(url, *args, **kwargs)
        res.raise_for_status()

        return Request.extract(res)
    
    @staticmethod
    def post(url: str, *args, **kwargs) -> Response: 
        res = requests.post(url, *args, **kwargs)
        res.raise_for_status()

        return Request.extract(res)

def load_json(data: str) -> Response: 
    data_json = json.loads(data)
    return Response(data_json)

class FileLions:     
    @staticmethod
    def eval_script(script: Tag) -> Response: 
        script_text = script.text

        if script_text.startswith("eval"): 
            script_text = "console.log" + script_text[4:]

        result = subprocess.run(
            ["node", "-e", script_text],
            capture_output=True,
            text=True
        )
        stdout = result.stdout.strip()

        links_match = re.search(r"var links=(.+?);", stdout)
        if not links_match: 
            raise Exception("No links available!")
        
        links = load_json(links_match.group(1))
        return links

    @staticmethod
    def extract_m3u8(url: str, referer: str): 
        headers = { 
            "referer": referer 
        }
        res = Request.get(url, headers=headers)

        soup = BeautifulSoup(res.text(), "html.parser")

        # cari semua <script> yang mengandung 'eval(' di teksnya
        script = soup.find("script", text=re.compile(r"eval\s*\("))
        if not script: 
            raise Exception("No eval script found!")
        
        m3u8_result = FileLions.eval_script(script)
        return m3u8_result

        

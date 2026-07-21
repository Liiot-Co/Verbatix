import os
import re

directory = "backend/app"

patterns = [
    # projects -> studios
    (re.compile(r'\bfrom projects\b', re.IGNORECASE), "from studios"),
    (re.compile(r'\bjoin projects\b', re.IGNORECASE), "join studios"),
    (re.compile(r'\binto projects\b', re.IGNORECASE), "into studios"),
    (re.compile(r'\bupdate projects\b', re.IGNORECASE), "update studios"),
    (re.compile(r'__tablename__ = "projects"'), '__tablename__ = "studios"'),
    
    # proyectos -> projects
    (re.compile(r'\bfrom proyectos\b', re.IGNORECASE), "from projects"),
    (re.compile(r'\bjoin proyectos\b', re.IGNORECASE), "join projects"),
    (re.compile(r'\binto proyectos\b', re.IGNORECASE), "into projects"),
    (re.compile(r'\bupdate proyectos\b', re.IGNORECASE), "update projects"),
    (re.compile(r'__tablename__ = "proyectos"'), '__tablename__ = "projects"'),
]

for root, dirs, files in os.walk(directory):
    if "__pycache__" in root: continue
    for f in files:
        if f.endswith(".py"):
            path = os.path.join(root, f)
            with open(path, "r") as file:
                content = file.read()
            
            new_content = content
            for pat, repl in patterns:
                new_content = pat.sub(repl, new_content)
                
            if new_content != content:
                with open(path, "w") as file:
                    file.write(new_content)
                print(f"Updated {path}")

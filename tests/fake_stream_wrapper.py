"""Translate legacy fake scenarios into the user-supplied Qwen result envelope."""
import json
import os
import subprocess
import sys
import uuid
session = str(uuid.uuid4())
def emit(**event):
    print(json.dumps(dict(event, uuid=str(uuid.uuid4()), session_id=session)), flush=True)
emit(type='system', subtype='init')
process = subprocess.run(sys.argv[1:], input=sys.stdin.buffer.read(), stdout=subprocess.PIPE,
                         env=dict(os.environ, FAKE_STREAM_WRAPPED='1'))
emit(type='result', subtype='success' if process.returncode == 0 else 'error',
     is_error=process.returncode != 0, result=process.stdout.decode('utf-8', errors='replace'))
sys.exit(process.returncode)

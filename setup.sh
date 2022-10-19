#!/bin/bash

python -m ensurepip --upgrade
python -m pip install -r requirements.txt
export ON_CLOUD=1
export DATABASE_URL=${DATABASE_URL%%\?*}
python herokuapp.py

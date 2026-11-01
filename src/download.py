from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests
import yaml
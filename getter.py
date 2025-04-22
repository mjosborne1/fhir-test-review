import json
import subprocess
import logging
import shutil
import os
from utils import get_config
from pathlib import Path

logger = logging.getLogger(__name__)

def get_npm_packages(mode,data_dir,config_file):
    logger.info(f'...getting npm package files from simplifier using mode {mode}')
    # Load package configuration from JSON file
    packages = get_config(config_file,key="packages")    
    
    # Check if npm module directory exists, create it if not
    npm_path = os.path.join(data_dir,"npm")

    if mode == "clean" and os.path.exists(npm_path):
        try:
            shutil.rmtree(npm_path)
            logging.info(f'...attempting to remove node modules: {npm_path}')
        except Exception as e:
            logging.error(f'Could not remove directory and files in {npm_path}: {e}')
    
    if not os.path.exists(npm_path):
        os.makedirs(npm_path)

    # Create a list of package folder paths to be returned
    path_list = []
    # Iterate over FHIR standards in config file
    for standard in packages:
        # Extract name and version from config file
        name = standard['name']
        version = standard['version']
        title = standard['title']

        canonical = f'{name}@{version}'
        module_path = os.path.join(npm_path,'node_modules')
        if not os.path.exists(module_path):
            os.makedirs(module_path)
        package_path = os.path.join(module_path,name)
        # canonical path should only exist if in dirty mode
        if not os.path.exists(package_path):
            # Construct npm command with registry and package info
            npm_cmd = f"npm --registry https://packages.simplifier.net install {canonical} --prefix {npm_path}"

            # Run npm command using subprocess module
            print(f"Downloading {title}: {name} ({version})...")
            try:
                subprocess.run(npm_cmd, shell=True, check=True)
                logger.info(f"{name} ({version}) downloaded successfully!")
            except subprocess.CalledProcessError as e:
                logger.error(f"Error downloading {name}: {e}")
        else:
            logger.info(f'...skipping existing npm package for {title}: {name} ({version})...')
        path_list.append(package_path)
    
    return path_list
        

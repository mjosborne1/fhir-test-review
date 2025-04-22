import argparse
import os
import sys
from  getter import get_npm_packages
from tester import run_terminology_check, run_capability_test
from utils import check_path, get_config
import logging
from datetime import datetime

def main():
    """
    Check terminology in the FHIR Test Data Repository json instances.
    FHIR Test Data is free to download from https://github.com/hl7au/au-fhir-test-data
    
    Keyword arguments:
    -j, --jsondir : path to json data folder where test data lives
    -o, --outdir : path for report generated as html
    """
    
    homedir=os.environ['HOME']
    parser = argparse.ArgumentParser()
    defaultpath=os.path.join(homedir,"Development","hl7au","mjo-au-fhir-test-data","au-fhir-test-data-set")
    defaultoutpath=os.path.join(homedir,"data","fhir-test-review")
    logger = logging.getLogger(__name__)
    parser.add_argument("-j", "--jsondir", help="JSON data folder", default=defaultpath)   
    parser.add_argument("-o", "--outdir", help="JSON data folder", default=defaultoutpath)   
    args = parser.parse_args()

    check_path(args.jsondir)

    # setup report output folder for html reports   
    outdir = args.outdir
    check_path(outdir)

    # Check test data folder exists
    jdir = args.jsondir
    check_path(jdir)
    ## Setup logging
    now = datetime.now() # current date and time
    ts = now.strftime("%Y%m%d-%H%M%S")
    FORMAT='%(asctime)s %(lineno)d : %(message)s'
    logging.basicConfig(format=FORMAT, filename=os.path.join('logs',f'ig-tx-check-{ts}.log'),level=logging.INFO)
    logger.info('Started')
    config_file = os.path.join(os.getcwd(),'config.json')
    # Get the initial config
    # config.json 
    #  - terminology server endpoint
    #  - exceptions for errors/warnings can be safely ignored or checked manually.    
    conf = get_config(config_file,"init")[0]
    endpoint = conf["endpoint"] 
    # First check that the tx server instance is up 
    http_stat = run_capability_test(endpoint)
    if http_stat != 200:
        logger.fatal(f'Capability test failed with status: {http_stat}')
        sys.exit(1)
    logger.info("Passed Capability test, continue on with other checks")

    # Run Example checks
    run_terminology_check(endpoint, config_file, jdir, outdir)
    logger.info("Finished")

if __name__ == '__main__':
    main()
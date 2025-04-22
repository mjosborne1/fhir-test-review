### About this script
The purpose of this script is to generate a Terminology Validation report about the [FHIR Test Data repo](https://github.com/hl7au/au-fhir-test-data). It may also be a fork of the repo. It is expected that the test data is downloaded locally and has a `au-fhir-test-data-set` folder containing json test data (FHIR instances) 

### Installation Requirements
- Python3 and the ability to install modules using pip. This will be automatic through the requirements file.
- A file path for the output of the process, on Windows this might be C:\data\fhir-test-review\ 
  on Mac/Linux it will be `/home/user/data/fhir-test-review` or similar where `user` is your account name


### How to install this script 
   * `git clone https://github.com/mjosborne1/fhir-test-review.git`
   * `cd fhir-test-review`
   * `virtualenv .venv`
   * `source ./.venv/bin/activate`
   * `pip install -r requirements.txt`

### How to run the script
   * Download the fhir test data. Note the `au-fhir-test-data-set` folder contains json resources generated at the time the test data was last updated, so this will be fine to use.
      `git clone https://github.com/hl7au/au-fhir-test-data`
   * ensure the virtual environment is set
      * Mac/Linux/WSL: `source ./.venv/bin/activate`
      * Windows CMD/Powershell: `.\.venv\Scripts\activate`
   * `python main.py --jsondir /path/to/test/data --outdir /path/to/report/output` 
   ```
        fhir-test-review % python main.py -h
        usage: main.py [-h] [-j JSONDIR] [-o OUTDIR]

        options:
        -h, --help            show this help message and exit
        -j JSON_DIR, --gendir JSON_DIR
        -o OUTPUT_DIR, --outdir OUTPUT_DIR
                               Report output folder
   ```    

### Output
   * Output is ...
      * an html file in the report output directory called `TestDataValidationReport.html`
      * an xlsx file in the report output directory called `TestDataValidationReport-{ts}.xlsx`
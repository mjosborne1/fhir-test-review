import os
import requests
from datetime import datetime
from os.path import isfile
import json
import glob
import pandas as pd
from urllib.parse import quote
from fhirpathpy import evaluate
from utils import get_config, split_node_path
import logging

logger = logging.getLogger(__name__)
SKIP_DIRS = ["assets", "temp", "templates"]
EXTS = ["json"]

logger = logging.getLogger(__name__)

##
## get_all_files: recursively find all files with a matching file extension
##
def get_all_files(root, exclude=SKIP_DIRS):
    for item in root.iterdir():
        if item.name in exclude:
            continue
        for ext in EXTS:
            if item.name.match(ext):
                yield item
        if item.is_dir():
            yield from get_all_files(item)

##
## get_json_files: find all json files 
##
def get_json_files(root,filter=None):
    if filter == None:
        pattern = "%s/*.json" % (root)
    else:
        pattern = "%s/%s*.json" % (root,filter)
    for item in glob.glob(pattern):
        if isfile(item):
            yield item


def validate_code_with_fhirpath(resource, fhirpath_expression, endpoint, cs_excluded, file):
    results = []
    codes = evaluate(resource, fhirpath_expression)
    for code_info in codes:
        if isinstance(code_info, dict):
            # Handle Coding/CodeableConcept structures
            system = code_info.get('system')
            display = code_info.get('display')
            code = code_info.get('code')
            
            # Get text from parent CodeableConcept by removing .coding from the path
            parent_path = fhirpath_expression.replace('.coding', '')
            text = evaluate(resource, f"{parent_path}.text")[0] if evaluate(resource, f"{parent_path}.text") else '-'
            
            if system and code and isinstance(system, str) and isinstance(code, str) and system.strip() and code.strip():
                result = validate_example_code(endpoint, cs_excluded, file, system, code)
                result['resourceType'] = evaluate(resource, "resourceType")[0]
                result['element'] = fhirpath_expression
                result['text'] = text
                results.append(result)
            else:
                logging.warning(f'Invalid system or code: system={system}, code={code}')
    return results


def validate_example_code(endpoint, cs_excluded, file, system, code):
    """
       Validate a code from an example resource instance
     
       Return: test_result dict , code and error
    """
    cmd = f'{endpoint}/CodeSystem/$validate-code?url='
    query = cmd + quote(system, safe='') + f'&code={code}'
    headers = {'Accept': 'application/fhir+json'}
    response = requests.get(query, headers=headers)
    data = response.json()
    display = evaluate(data, "parameter.where(name = 'display').valueString")[0] if evaluate(data, "parameter.where(name = 'display').valueString") else None
    test_result = {
        'file': split_node_path(file),
        'code': code,
        'display': display,
        'system': system,
        'status_code': response.status_code,
        'reason': ''
    }
    excluded = False
    for exc in cs_excluded:
        if exc["uri"] == system:
            test_result['result'] = exc['result']
            test_result['reason'] = exc['reason']
            excluded = True
            break
    if not excluded:
        if response.status_code == 200:
            if evaluate(data, "parameter.where(name = 'result').valueBoolean")[0]:
                test_result['result'] = 'PASS'
            else:
                test_result['result'] = 'FAIL'
                test_result['reason'] = 'Not a valid code'
        else:
            test_result['result'] = 'FAIL'
            test_result['reason'] = f'http status: {response.status_code}'
    return test_result


##
## search_json_file: search a json file for FHIR coding elements
##

def search_json_file(endpoint, cs_excluded, file):
    with open(file, 'r') as f:
        resource = json.load(f)

    fhirpath_expressions = [
        "category.coding",
        "code.coding",
        "coding",
        "type.coding",
        "status",
        "priority.coding",
        "severity.coding",
        "clinicalStatus.coding",
        "verificationStatus.coding",
        "intent.coding",
        "use.coding",
        "action.coding",
        "outcome.coding",
        "subType.coding",
        "reasonCode.coding",
        "route.coding",
        "vaccineCode.coding",
        "medicationCodeableConcept.coding",
        "bodySite.coding",
        "relationship.coding",
        "sex.coding",
        "morphology.coding",
        "location.coding",
        "format.coding",
        "class.coding",
        "modality.coding",
        "jurisdiction.coding",
        "topic.coding",
        "contentType.coding",
        "connectionType.coding",
        "operationalStatus.coding",
        "color.coding",
        "measurementPeriod.coding",
        "doseQuantity.coding",
        "substanceCodeableConcept.coding",
        "valueCodeableConcept.coding",
        "valueCoding",
        "valueQuantity.coding",
        "ingredient.itemCodeableConcept.coding",
        "dosageInstruction.route.coding",
        "ingredient.quantity",
        "ingredient.quantity.numerator",
        "ingredient.quantity.denominator"
    ]

    test_result_list = []
    for expression in fhirpath_expressions:
        results = validate_code_with_fhirpath(resource, expression, endpoint, cs_excluded, file)
        if results:            
            test_result_list.extend(results)

    return test_result_list


def run_capability_test(endpoint):
    """
       Fetch the capability statement from the endpoint and assert it 
       instantiates http://hl7.org/fhir/CapabilityStatement/terminology-server
    """
    query = f'{endpoint}/metadata'
    headers = {'Accept': 'application/fhir+json'}
    response = requests.get(query, headers=headers)
    if response.status_code == 200:
        data = response.json()
        server_type = evaluate(data, "instantiates[0]")
        fhirVersion = evaluate(data, "fhirVersion")
        if server_type[0] == "http://hl7.org/fhir/CapabilityStatement/terminology-server" and fhirVersion[0] == "4.0.1":
            return 200  # OK
        else:
            return 418  # I'm a teapot (have we upgraded to a new version??)
    else:
        return response.status_code   # I'm most likely offline


def run_terminology_check(endpoint, testconf, jdir, outdir):
    """
      Test that the IG example instance codes are in the terminology server
      results of the checks reported in an html file
    """
    now = datetime.now() # current date and time
    ts = now.strftime("%Y%m%d-%H%M%S")
    html_file = os.path.join(outdir, 'TestDataValidationReport.html')  
    excel_file = os.path.join(outdir, f'TestDataValidationReport-{ts}.xlsx')
    cs_excluded = get_config(testconf, 'codesystem-excluded')
    all_results = []

    
    for instance in get_json_files(jdir):
        logger.info(f'...{instance}')
        results = search_json_file(endpoint, cs_excluded, instance)
        all_results.extend(results)

    # Output as HTML  
    # Flatten the list of lists

    header = ['file','resourceType','element','code','display','text','system','result','reason']
    df_results = pd.DataFrame(all_results, columns=header)
    exit_status = 1 if (df_results['result'] == 'FAIL').any() else 0
    html_content = df_results.to_html()

    with open(html_file, "w") as fh:
        fh.write(html_content)

    # Generate Excel output
    writer = pd.ExcelWriter(excel_file, engine='xlsxwriter')
    df_results.to_excel(writer, sheet_name='Terminology Checks', index=False)
    
    # Get workbook and worksheet objects for formatting
    workbook = writer.book
    worksheet = writer.sheets['Terminology Checks']
    
    # Add column formatting
    code_format = workbook.add_format({'num_format': '@'})  # Text format for codes
    worksheet.set_column('D:D', 20, code_format)  # Apply to code column
    worksheet.set_column('A:I', 20)  # Set width for all columns

    # Get the actual number of rows in the data
    last_row = len(df_results) + 1  # Add 1 for the header row

    # Color formatting for PASS/FAIL
    worksheet.conditional_format(f'G2:G{last_row}', {'type': 'cell',
                                       'criteria': '==',
                                       'value': '"PASS"',
                                       'format': workbook.add_format({'bg_color': '#C6EFCE'})})
    worksheet.conditional_format(f'G2:G{last_row}', {'type': 'cell',
                                       'criteria': '==',
                                       'value': '"FAIL"',
                                       'format': workbook.add_format({'bg_color': '#FFC7CE'})})
    
    writer.close()
    
    exit_status = 1 if (df_results['result'] == 'FAIL').any() else 0
    return exit_status


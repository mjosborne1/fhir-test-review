import os
import re
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


def get_json_files(root,filter=None):
    """
    find all json files 
    """
    
    if filter == None:
        pattern = "%s/*.json" % (root)
    else:
        pattern = "%s/%s*.json" % (root,filter)
    for item in glob.glob(pattern):
        if isfile(item):
            yield item


def _extract_and_validate_elements(element, file_path, endpoint, cs_excluded, resource_id, current_path, current_file_results, parent_is_codeable_concept=False, cc_text=None):
    """
    Recursively extracts and validates coded elements from a FHIR resource fragment.
    """
    if isinstance(element, dict):
        system = element.get('system')
        code = element.get('code')
        display = element.get('display')
        # Check if the current path suggests this is a coding element
        is_coding = current_path and re.search(r'coding\[\d+\]$', current_path.lower())
        
        # Check for Coding element
        if is_coding:
            # Use cc_text passed down if the parent was a CodeableConcept
            context_text = cc_text if parent_is_codeable_concept else None
            # Validate and get the result dictionary
            test_result = validate_example_code(file_path, endpoint, cs_excluded, system, code, display, context_text, resource_id, current_path)
            # Append the single result dictionary to the list
            current_file_results.append(test_result)
            if display and not system and not code:
                current_file_results.append({
                    'file': split_node_path(file_path),
                    'resource_id': resource_id,
                    'path': current_path,
                    'code': None,
                    'display_provided': display,
                    'text_context': cc_text,
                    'system': None,
                    'result': 'ERROR',
                    'reason': 'Display provided but code and system are missing.',
                    'status_code': None
                })           
            elif display and not system:
                current_file_results.append({
                    'file': split_node_path(file_path),
                    'resource_id': resource_id,
                    'path': current_path,
                    'code': None,
                    'display_provided': display,
                    'text_context': cc_text,
                    'system': None,
                    'result': 'ERROR',
                    'reason': 'Display provided but system is missing.',
                    'status_code': None
                })  
            elif display and not code:
                current_file_results.append({
                    'file': split_node_path(file_path),
                    'resource_id': resource_id,
                    'path': current_path,
                    'code': None,
                    'display_provided': display,
                    'text_context': cc_text,
                    'system': None,
                    'result': 'ERROR',
                    'reason': 'Display provided but code is missing.',
                    'status_code': None
                })  
        # Check for CodeableConcept structure AFTER checking for Coding
        # A CodeableConcept might contain other nested elements to recurse into.
        is_codeable_concept = 'coding' in element and isinstance(element['coding'], list)
        current_concept_text_for_children = element.get('text') if is_codeable_concept else None

        # Special Case: CodeableConcept with only text (no 'coding' array or empty 'coding' array)
        # This might also match simple elements like "status": "active", so be careful.
        # We primarily rely on finding Coding elements inside the 'coding' array.
        # Let's add a check for CCs that might *only* have text.
        if not is_coding and element.get('text') and 'coding' in element and not element['coding']:
                current_file_results.append({
                'file': split_node_path(file_path),
                'resource_id': resource_id,
                'path': current_path,
                'code': None,
                'display_provided': None,
                'text_context': element.get('text'),
                'system': None,
                'result': 'INFO',
                'reason': 'CodeableConcept with text only, no codings.',
                'status_code': None
            })


        # Recurse through dictionary values
        for key, value in element.items():
            new_path = f"{current_path}.{key}" if current_path else key
            if key == 'coding' and isinstance(value, list) and is_codeable_concept:
                # Processing the 'coding' array within a CodeableConcept
                for i, item in enumerate(value): # item should be a Coding dictionary
                    item_path = f"{new_path}[{i}]"
                    # Pass the CC's text down; the item itself is a Coding, so parent_is_cc is True
                    _extract_and_validate_elements(item, file_path, endpoint, cs_excluded, resource_id, item_path, current_file_results, parent_is_codeable_concept=True, cc_text=current_concept_text_for_children)
            elif isinstance(value, (dict, list)): # Only recurse into dicts or lists
                    # Pass current_concept_text_for_children only if the CURRENT element (element) is a CC
                    _extract_and_validate_elements(value, file_path, endpoint, cs_excluded, resource_id, new_path, current_file_results, parent_is_codeable_concept=is_codeable_concept, cc_text=current_concept_text_for_children if is_codeable_concept else None)

    elif isinstance(element, list):
        # Recurse through list items
        for i, item in enumerate(element):
            item_path = f"{current_path}[{i}]"
            # Carry forward parent_is_codeable_concept status and cc_text from the element containing the list
            _extract_and_validate_elements(item, file_path, endpoint, cs_excluded, resource_id, item_path, current_file_results, parent_is_codeable_concept=parent_is_codeable_concept, cc_text=cc_text)


def parse_validate_code_response(response_json):
    """
    Parses the JSON response (FHIR Parameters) from a $validate-code operation.

    Args:
        response_json (dict): The parsed JSON response.

    Returns:
        tuple: (is_valid, display, message)
               is_valid (bool or None): True if valid, False if invalid, None if result not found.
               display (str or None): The canonical display from the server, or None.
               message (str or None): The message from the server, or None.
    """
    is_valid = None
    display = None
    message = None

    if not isinstance(response_json, dict) or response_json.get('resourceType') != 'Parameters':
        return None, None, "Invalid response format: Not a Parameters resource."

    parameters = response_json.get('parameter', [])

    for param in parameters:
        if isinstance(param, dict):
            name = param.get('name')
            if name == 'result':
                is_valid = param.get('valueBoolean') # Should be True or False
            elif name == 'display':
                display = param.get('valueString')
            elif name == 'message':
                message = param.get('valueString')

    return is_valid, display, message


def validate_example_code(file_path, endpoint, cs_excluded, system, code, display_provided, code_text, resource_id, current_path):
    """
    Validates a code from an example resource instance against a FHIR terminology server.

    Args:
        file_path (str): Path to the source file.
        endpoint (str): Base URL of the FHIR terminology server.
        cs_excluded (list): List of excluded code system config dicts.
        system (str): The code system URI.
        code (str): The code value.
        display_provided (str): The display text provided in the instance.
        code_text (str): The text from the parent CodeableConcept (if applicable).
        resource_id (str): ID of the resource instance.
        current_path (str): JSON path to the element.

    Returns:
        dict: A dictionary containing the validation result.
    """
    base_file_name = split_node_path(file_path)
    test_result = {
        'file': base_file_name,
        'resource_id': resource_id,
        'path': current_path,
        'code': code,
        'display_provided': display_provided, # Keep the original display
        'text_context': code_text, # Text from parent CC
        'system': system,
        'result': 'UNKNOWN', # Default status
        'reason': '',
        'status_code': None
    }

    # 1. Check if system is excluded
    for exc in cs_excluded:
        if isinstance(exc, dict) and exc.get("uri") == system:
            test_result['result'] = exc.get('result', 'EXCLUDED') # Use configured result or default
            test_result['reason'] = exc.get('reason', 'Code system is excluded from validation.')
            logger.debug(f"Code system '{system}' excluded for code '{code}' in {base_file_name} at {current_path}.")
            return test_result # Stop validation if excluded

    # 2. Check for missing code when display is provided
    if display_provided and not code:
        test_result['result'] = 'ERROR'
        test_result['reason'] = "Display provided but code is missing."
        logger.error(f"Display provided but code is missing in {base_file_name} at {current_path}.")
        return test_result
    
    # 3. Prepare and send request
    if not endpoint.endswith('/'):
        endpoint += '/'
    # Use parameters for requests library to handle encoding
    params = {'url': system, 'code': code}
    # Optionally add display for validation if server supports it well via GET
    # params['display'] = display_provided # Uncomment if you want to validate display this way
    query_url = f'{endpoint}CodeSystem/$validate-code'
    headers = {'Accept': 'application/fhir+json', 'User-Agent': 'FHIR-Terminology-Validator-Client/1.0'} # Good practice to add User-Agent

    try:
        response = requests.get(query_url, headers=headers, params=params, timeout=15) # Added timeout
        test_result['status_code'] = response.status_code
        response.raise_for_status() # Raises HTTPError for 4xx/5xx responses

        # 3. Process successful response (200 OK)
        data = response.json()
        is_valid, server_display, message = parse_validate_code_response(data)

        if is_valid is True:
            test_result['result'] = 'PASS'
            test_result['reason'] = message or "Code is valid."
             # Optional: Check if provided display matches server display
            if display_provided and server_display and display_provided != server_display:
                 test_result['reason'] += f" Provided display ('{display_provided}') differs from server display ('{server_display}')."
            elif display_provided and not server_display:
                 test_result['reason'] += f" Server did not return a display for comparison with provided display ('{display_provided}')."

        elif is_valid is False:
            test_result['result'] = 'FAIL'
            test_result['reason'] = message or "Code is not valid according to the terminology server."
        else: # Result parameter was missing or not boolean
            test_result['result'] = 'ERROR'
            test_result['reason'] = message or "Validation response missing 'result' parameter or it was not boolean."

    except requests.exceptions.HTTPError as e:
        test_result['result'] = 'ERROR' # Changed from FAIL for HTTP errors
        test_result['reason'] = f"HTTP Error: {e.response.status_code} {e.response.reason}."
        # Attempt to get more details from response body if available
        try:
            error_details = e.response.json()
            # Look for OperationOutcome details
            oo_text = error_details.get("text", {}).get("div", "No details provided.")
            oo_issue = error_details.get("issue", [{}])[0].get("diagnostics", "No diagnostics.")
            test_result['reason'] += f" Details: {oo_text} / {oo_issue}"
        except (json.JSONDecodeError, AttributeError, KeyError, IndexError):
            test_result['reason'] += f" Response Body: {e.response.text[:200]}" # Limit response text length

    except requests.exceptions.Timeout:
        test_result['result'] = 'ERROR'
        test_result['reason'] = "Request timed out."
        test_result['status_code'] = 408 # Request Timeout status code
    except requests.exceptions.RequestException as e:
        test_result['result'] = 'ERROR'
        test_result['reason'] = f"Request Exception: {e}"
    except json.JSONDecodeError:
         test_result['result'] = 'ERROR'
         test_result['reason'] = "Invalid JSON response from server."
    except Exception as e: # Catch unexpected errors during processing
        logger.error(f"Unexpected error during validation for {system}|{code}: {e}", exc_info=True)
        test_result['result'] = 'ERROR'
        test_result['reason'] = f"Unexpected validation error: {e}"


    logger.debug(f"Validation result for {system}|{code} at {current_path}: {test_result['result']} - {test_result['reason']}")
    return test_result

##
## search_json_file: search a json file for FHIR coding elements
##

def search_json_file(endpoint, cs_excluded, file):
    file_results = []
    with open(file, 'r') as f:
        resource = json.load(f)
        resource_id = resource.get('id', 'UnknownID')
        resource_type = resource.get('resourceType', 'UnknownType')
        _extract_and_validate_elements(resource, file, endpoint, cs_excluded, resource_id, resource_type, file_results, parent_is_codeable_concept=False, cc_text=None)

    return file_results


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
    Tests that the IG example instance codes are valid against a terminology server,
    reporting results in HTML and Excel files.

    Args:
        endpoint (str): Base URL of the FHIR terminology server.
        testconf (any): Configuration source (e.g., dict, file path) for exclusions.
        jdir (str): Directory containing FHIR JSON example instances.
        outdir (str): Directory to save the report files.

    Returns:
        int: Exit status (0 for success/no fails, 1 if any fails occurred).
    """
    if not os.path.exists(outdir):
        os.makedirs(outdir)
        logger.info(f"Created output directory: {outdir}")

    now = datetime.now() # current date and time
    ts = now.strftime("%Y%m%d-%H%M%S")
    html_file = os.path.join(outdir, 'TestDataValidationReport.html')
    excel_file = os.path.join(outdir, f'TestDataValidationReport-{ts}.xlsx')

    cs_excluded = get_config(testconf, 'codesystem-excluded')
    if cs_excluded is None:
        logger.warning("Could not load 'codesystem-excluded' configuration. No systems will be excluded.")
        cs_excluded = []

    all_results = [] # Master list to hold all results from all files

    logger.info(f"Starting terminology validation against: {endpoint}")
    logger.info(f"Processing files in: {jdir}")
    logger.info(f"Excluded systems: {cs_excluded if cs_excluded else 'None'}")

    for instance_file in get_json_files(jdir):
        logger.info(f"...processing instance: {split_node_path(instance_file)}")
        try:
            # search_json_file now returns results for *just this file*
            file_results = search_json_file(endpoint, cs_excluded, instance_file)
            if file_results: # Only extend if results were found
                 all_results.extend(file_results)
        except FileNotFoundError:
            logger.error(f"File not found: {instance_file}. Skipping.")
        except json.JSONDecodeError:
            logger.error(f"Invalid JSON in file: {instance_file}. Skipping.")
            all_results.append({ # Add an error entry for reporting
                'file': split_node_path(instance_file),
                'resource_id': 'N/A',
                'path': 'File Level',
                'code': None, 'display': None, 'text': None, 'system': None,
                'result': 'ERROR',
                'reason': 'Invalid JSON format',
                'status_code': None
            })
        except Exception as e:
            logger.error(f"Unexpected error processing file {instance_file}: {e}", exc_info=True)
            all_results.append({ # Add an error entry for reporting
                'file': split_node_path(instance_file),
                'resource_id': 'N/A',
                'path': 'File Level',
                'code': None, 'display': None, 'text': None, 'system': None,
                'result': 'ERROR',
                'reason': f'Unexpected error: {str(e)}',
                'status_code': None
            })


    # --- Output Results ---
    if not all_results:
        logger.warning("No coded elements found or processed in any files.")
        # Create empty files or just return? Let's create empty reports.
        header = ['file', 'resource_id', 'path', 'code', 'display_provided', 'text_context', 'system', 'result', 'reason', 'status_code']
        df_results = pd.DataFrame([], columns=header)
        exit_status = 0 # No failures if no results
    else:
        # Define header based on keys returned by validate_example_code
        # Ensure validate_example_code returns these consistently
        header = ['file', 'resource_id', 'path', 'code', 'display_provided', 'text_context', 'system', 'result', 'reason', 'status_code']
        df_results = pd.DataFrame(all_results)
        # Ensure all expected columns exist, fill missing with None or appropriate default if necessary
        for col in header:
            if col not in df_results.columns:
                df_results[col] = None
        df_results = df_results[header] # Reorder columns to match header

        # Determine exit status: 1 if any 'FAIL' exists, 0 otherwise
        # Exclude ERROR results from causing a non-zero exit code unless desired
        exit_status = 1 if (df_results['result'] == 'FAIL').any() else 0

    logger.info(f"Validation complete. Total results: {len(df_results)}. Fails found: {(df_results['result'] == 'FAIL').sum()}.")

    # Output as HTML
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


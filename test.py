import pandas as pd
import unittest
from utils import get_config, check_path
import os
from tester import run_capability_test
from tester import validate_example_code, get_json_files, search_json_file



class TestValueSetTester(unittest.TestCase):
    def setUp(self):
        ## Shared config
        self.homedir=os.environ['HOME']           
        self.path_default=os.path.join(self.homedir,"data","fhir-test-review")
        self.test_config_default = os.path.join(os.getcwd(),"config.json")
        conf = get_config(self.test_config_default,"init")[0]
        self.endpoint = conf['endpoint']
        self.assertNotEqual(self.endpoint,'')
        self.test_outdir = os.path.join(self.path_default,"unittests")
        check_path(self.test_outdir)
        self.example_dir = os.path.join(os.getcwd(),"config","examples")
        check_path(self.example_dir)
        pass

    def test_server_capability(self):
        """
           Test that the server is up and is a terminology server
        """
        status = run_capability_test(self.endpoint)
        self.assertEqual(status,200)

    def test_check_coding(self):
        """
            Test that the example codes in the some of the instance examples validate correctly
        """
        cs_excluded = get_config(self.test_config_default,'codesystem-excluded')  
        example_list = get_json_files(self.example_dir)
        all_results = []
        for ex in example_list:
            results = search_json_file(self.endpoint, cs_excluded, ex)
            all_results.extend(results)
        header = ['file','resourceType','element','code','display','text','system','result','reason']
        df_results = pd.DataFrame(all_results,columns=header)
        self.assertFalse((df_results['result']=='FAIL').any())
        

    def test_validate_code(self):
        """
            Test that Validate code returns true / false as the case warrants
            Tests both the request status and the response for the validation
        """       
        tests = [
            {'file': 'file1.json', 'system': 'http://snomed.info/sct', 'code': '79115011000036100', 'status_code': 200, 'result': 'PASS'}, 
            {'file': 'file1.json', 'system': 'http://loinc.org', 'code': '16935-9' , 'status_code': 200, 'result': 'PASS'},
            {'file': 'file2.json', 'system': 'http://loinc.org', 'code': '6935-9' , 'status_code': 200, 'result': 'FAIL' }
        ]
        cs_excluded = get_config(self.test_config_default,'codesystem-excluded')        
        for test in tests: 
            result_status = validate_example_code(self.endpoint,cs_excluded,test['file'],test['system'],test['code'])
            self.assertEqual(test['status_code'], result_status['status_code'])
            self.assertEqual(test['result'], result_status['result'])

if __name__ == '__main__':
    unittest.main()

"""Small fixed Appium W3C client; no shell or route-provided script endpoint."""
import base64, hashlib, json, re, subprocess, urllib.request, urllib.error, urllib.parse
from .protocol import PACKAGE, package_name
ELEMENT='element-6066-11e4-a52e-4f735466cecf'
class Uncertain(RuntimeError): pass
class TargetNotForeground(RuntimeError): pass

class Appium:
    def __init__(self,device,package,url='http://127.0.0.1:4723',*,session_create_timeout=90):
        if not re.fullmatch(r'[A-Za-z0-9_.:-]{1,128}',device): raise ValueError('Explicit valid device serial required')
        package_name(package)
        u=urllib.parse.urlparse(url)
        if u.scheme!='http' or u.hostname not in ['127.0.0.1','localhost'] or u.path not in ['', '/'] or u.username or u.query or u.fragment: raise ValueError('Appium must be local')
        if type(session_create_timeout) is not int or not 30<=session_create_timeout<=300: raise ValueError('Session creation timeout must be an integer from 30 to 300 seconds')
        self.device=device; self.package=package; self.url=url.rstrip('/'); self.session=None; self.uncertain=False
        self.session_create_timeout=session_create_timeout
    def request(self,method,path,data=None):
        req=urllib.request.Request(self.url+path,data=None if data is None else json.dumps(data).encode(),headers={'Content-Type':'application/json'},method=method)
        # Creating a session includes helper setup and instrumentation startup.
        # Keep ordinary input/observation/DELETE requests on the shorter budget.
        timeout=self.session_create_timeout if (method,path)==('POST','/session') else 20
        try:
            # Ignore ambient proxy configuration for the local automation server.
            with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req,timeout=timeout) as r: value=json.load(r).get('value')
        except urllib.error.HTTPError as e:
            raise RuntimeError('Appium HTTP %s: %s'%(e.code,e.read(2048).decode(errors='replace'))) from e
        except (TimeoutError,OSError,ValueError) as e:
            self.uncertain=True; raise Uncertain('Transport result unknown; never retry input automatically') from e
        if isinstance(value,dict) and value.get('error'): raise RuntimeError(str(value))
        return value
    def call(self,method,path,data=None):
        if not self.session: raise RuntimeError('No Appium session')
        return self.request(method,'/session/'+self.session+path,data)
    def adb(self,*args,binary=False):
        result=subprocess.run(['adb','-s',self.device,*args],capture_output=True,timeout=20,check=True)
        return result.stdout if binary else result.stdout.decode(errors='strict').strip()
    def target(self):
        if self.adb('get-state')!='device': raise RuntimeError('Selected device not ready')
        info=self.adb('shell','dumpsys','package',self.package)
        code=re.search(r'versionCode=(\d+)',info); name=re.search(r'versionName=([^\s]+)',info)
        paths=self.adb('shell','pm','path',self.package).splitlines()
        if self.package!=PACKAGE:
            if not code or not name or not paths or len(paths)>200: raise RuntimeError('Installed package metadata unavailable')
            hashes={}
            for item in sorted(paths):
                if not re.fullmatch(r'package:/[A-Za-z0-9/_.=+~@-]+\.apk',item): raise RuntimeError('Unsupported installed APK path')
                basename=item.rsplit('/',1)[-1]
                if basename in hashes: raise RuntimeError('Duplicate APK manifest name')
                hashes[basename]=hashlib.sha256(self.adb('exec-out','cat',item[8:],binary=True)).hexdigest()
            return {'version_code':code[1],'version_name':name[1],'apk_sha256s':hashes}
        if len(paths)!=1 or not paths[0].startswith('package:/data/app/') or not re.fullmatch(r'package:[A-Za-z0-9/_.=+~-]+\.apk',paths[0]): raise RuntimeError('Single installed APK required')
        digest=hashlib.sha256(self.adb('exec-out','cat',paths[0][8:],binary=True)).hexdigest()
        if not code or not name or (code[1],name[1])!=('1','1.0'): raise RuntimeError('Unexpected fixture build')
        return {'version_code':code[1],'version_name':name[1],'apk_sha256':digest}
    def launcher(self):
        output=self.adb('shell','cmd','package','resolve-activity','--brief','-a','android.intent.action.MAIN','-c','android.intent.category.LAUNCHER',self.package)
        matches=[line for line in output.splitlines() if re.fullmatch(re.escape(self.package)+r'/[A-Za-z0-9_.$]+',line)]
        if len(matches)!=1: raise RuntimeError('No unique launcher activity; app may not be launchable in this user profile')
        return matches[0]
    def preflight(self):
        return {'device':self.device,'package':self.package,'launcher':self.launcher(),'target':self.target(),
                'hidden_api':{key:self.adb('shell','settings','get','global',key) for key in ('hidden_api_policy_pre_p_apps','hidden_api_policy_p_apps','hidden_api_policy')},
                'helper_mock_location':self.adb('shell','cmd','appops','get','io.appium.settings','android:mock_location')}
    def approve_security(self,report):
        if report['package']!=self.package:raise ValueError('Preflight package mismatch')
        policies=report['hidden_api']
        if any(v not in ('null','0','1','2') for v in policies.values()):raise RuntimeError('Unsupported security baseline; manual review required')
        match=re.search(r'(?:MOCK_LOCATION|mock_location): (allow|ignore|deny|default|foreground)',report['helper_mock_location'])
        if not match and 'No operations' not in report['helper_mock_location']:raise RuntimeError('Cannot determine helper permission baseline')
        self.security_baseline=(dict(policies),match[1] if match else 'default');self.security_approved=True
    def restore_security(self):
        if not hasattr(self,'security_baseline'):return
        if self.uncertain:raise RuntimeError('Transport uncertain: stop Appium before manual baseline recovery; baseline retained')
        policies,mode=self.security_baseline
        for key,value in policies.items():
            if value=='null':self.adb('shell','settings','delete','global',key)
            else:self.adb('shell','settings','put','global',key,value)
            if self.adb('shell','settings','get','global',key)!=value:raise RuntimeError('Security restoration verification failed: '+key)
        self.adb('shell','cmd','appops','set','io.appium.settings','android:mock_location',mode)
        observed=self.adb('shell','cmd','appops','get','io.appium.settings','android:mock_location')
        if not re.search(r'(?:MOCK_LOCATION|mock_location): '+mode+r'\b',observed) and not (mode=='default' and 'No operations' in observed):raise RuntimeError('Mock location restoration verification failed')
        del self.security_baseline;self.security_approved=False
    def launch(self):
        component=self.launcher()
        result=self.adb('shell','am','start','-W','-a','android.intent.action.MAIN','-c','android.intent.category.LAUNCHER','-n',component)
        if 'Status: ok' not in [line.strip() for line in result.splitlines()]: raise RuntimeError('Launcher did not report successful start')
        return 'Launcher started; visual entry and login state not verified'
    def open(self):
        if self.package!=PACKAGE and not getattr(self,'security_approved',False):raise RuntimeError('Review preflight and approve temporary Appium security effects first')
        self.snapshot=self.target()
        activity='.MainActivity' if self.package==PACKAGE else self.launcher().split('/',1)[1]
        caps={'platformName':'Android','appium:automationName':'UiAutomator2','appium:udid':self.device,'appium:deviceName':self.device,'appium:appPackage':self.package,'appium:appActivity':activity,'appium:noReset':True,'appium:forceAppLaunch':False,'appium:newCommandTimeout':120,'appium:adbExecTimeout':15000,'appium:uiautomator2ServerReadTimeout':15000,'appium:uiautomator2ServerLaunchTimeout':15000,'appium:skipDeviceInitialization':False}
        if self.package!=PACKAGE:caps['appium:autoLaunch']=False
        v=self.request('POST','/session',{'capabilities':{'alwaysMatch':caps}})
        self.session=v['sessionId']; self.call('POST','/timeouts',{'implicit':0})
    def close(self):
        if self.session:
            self.call('DELETE',''); self.session=None
        self.restore_security()
    def foreground(self):
        if self.call('GET','/appium/device/current_package')!=self.package: raise TargetNotForeground('Target is not foreground')
    def geometry(self):
        r=self.call('GET','/window/rect'); rotation=self.call('GET','/orientation')
        return {'width':r['width'],'height':r['height'],'rotation':rotation}
    def elements(self,resource):
        return [e[ELEMENT] for e in self.call('POST','/elements',{'using':'id','value':resource})]
    def text(self,element): return self.call('GET','/element/'+element+'/text')
    def source(self): return self.call('GET','/source')
    def screenshot(self): return base64.b64decode(self.call('GET','/screenshot'),validate=True)
    def click(self,e): self.call('POST','/element/'+e+'/click',{})
    def check_text_target(self,e):
        value=self.call('GET','/element/'+e+'/attribute/password')
        if value not in (False,'false'):raise RuntimeError('Password or unknown text field rejected before intent storage')
    def enter(self,e,text):
        self.call('POST','/element/'+e+'/clear',{})
        self.call('POST','/element/'+e+'/value',{'text':text})
    def back(self): self.call('POST','/back',{})
    def gesture(self,start,end=None):
        moves=[{'type':'pointerMove','duration':0,'x':start[0],'y':start[1],'origin':'viewport'}, {'type':'pointerDown','button':0}]
        if end: moves += [{'type':'pointerMove','duration':500,'x':end[0],'y':end[1],'origin':'viewport'}]
        else: moves += [{'type':'pause','duration':80}]
        moves += [{'type':'pointerUp','button':0}]
        self.call('POST','/actions',{'actions':[{'type':'pointer','id':'finger','parameters':{'pointerType':'touch'},'actions':moves}]})

"""Small fixed Appium W3C client; no shell or route-provided script endpoint."""
import base64, hashlib, json, re, subprocess, urllib.request, urllib.error, urllib.parse
from .protocol import PACKAGE
ELEMENT='element-6066-11e4-a52e-4f735466cecf'
class Uncertain(RuntimeError): pass

class Appium:
    def __init__(self,device,package,url='http://127.0.0.1:4723',*,session_create_timeout=90):
        if not re.fullmatch(r'[A-Za-z0-9_.:-]{1,128}',device): raise ValueError('Explicit valid device serial required')
        if package!=PACKAGE: raise ValueError('Only synthetic package supported')
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
        if len(paths)!=1 or not paths[0].startswith('package:/data/app/') or not re.fullmatch(r'package:[A-Za-z0-9/_.=+~-]+\.apk',paths[0]): raise RuntimeError('Single installed APK required')
        digest=hashlib.sha256(self.adb('exec-out','cat',paths[0][8:],binary=True)).hexdigest()
        if not code or not name or (code[1],name[1])!=('1','1.0'): raise RuntimeError('Unexpected fixture build')
        return {'version_code':code[1],'version_name':name[1],'apk_sha256':digest}
    def open(self):
        self.snapshot=self.target()
        v=self.request('POST','/session',{'capabilities':{'alwaysMatch':{'platformName':'Android','appium:automationName':'UiAutomator2','appium:udid':self.device,'appium:deviceName':self.device,'appium:appPackage':self.package,'appium:appActivity':'.MainActivity','appium:noReset':True,'appium:forceAppLaunch':False,'appium:newCommandTimeout':120,'appium:adbExecTimeout':15000,'appium:uiautomator2ServerReadTimeout':15000,'appium:uiautomator2ServerLaunchTimeout':15000,'appium:skipDeviceInitialization':False}}})
        self.session=v['sessionId']; self.call('POST','/timeouts',{'implicit':0})
    def close(self):
        if self.session:
            self.call('DELETE',''); self.session=None
    def foreground(self):
        if self.call('GET','/appium/device/current_package')!=self.package: raise RuntimeError('Target is not foreground')
    def geometry(self):
        r=self.call('GET','/window/rect'); rotation=self.call('GET','/orientation')
        return {'width':r['width'],'height':r['height'],'rotation':rotation}
    def elements(self,resource):
        return [e[ELEMENT] for e in self.call('POST','/elements',{'using':'id','value':resource})]
    def text(self,element): return self.call('GET','/element/'+element+'/text')
    def source(self): return self.call('GET','/source')
    def screenshot(self): return base64.b64decode(self.call('GET','/screenshot'),validate=True)
    def click(self,e): self.call('POST','/element/'+e+'/click',{})
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

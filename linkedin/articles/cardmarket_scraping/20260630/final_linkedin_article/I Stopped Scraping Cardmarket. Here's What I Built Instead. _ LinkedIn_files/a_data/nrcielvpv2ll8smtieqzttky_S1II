!function(){var t,e=void 0,n=!0,i=null,a=!1,r=this
function o(t,e){function n(){}n.prototype=e.prototype
t.X=e.prototype
t.prototype=new n
t.prototype.constructor=t}function s(){}function h(t,e,n){switch(typeof e){case"string":f(e,n)
break
case"number":n.push(isFinite(e)&&!isNaN(e)?e:"null")
break
case"boolean":n.push(e)
break
case"undefined":n.push("null")
break
case"object":if(e==i){n.push("null")
break}if("array"==function(t){var e=typeof t
if("object"==e){if(!t)return"null"
if(t instanceof Array)return"array"
if(t instanceof Object)return e
var n=Object.prototype.toString.call(t)
if("[object Window]"==n)return"object"
if("[object Array]"==n||"number"==typeof t.length&&void 0!==t.splice&&void 0!==t.propertyIsEnumerable&&!t.propertyIsEnumerable("splice"))return"array"
if("[object Function]"==n||void 0!==t.call&&void 0!==t.propertyIsEnumerable&&!t.propertyIsEnumerable("call"))return"function"}else if("function"==e&&void 0===t.call)return"object"
return e}(e)){var a=e.length
n.push("[")
for(var r="",o=0;o<a;o++)n.push(r),h(t,e[o],n),r=","
n.push("]")
break}n.push("{")
a=""
for(r in e)Object.prototype.hasOwnProperty.call(e,r)&&("function"!=typeof(o=e[r])&&(n.push(a),f(r,n),n.push(":"),h(t,o,n),a=","))
n.push("}")
break
case"function":break
default:throw Error("Unknown type: "+typeof e)}}var c={'"':'\\"',"\\":"\\\\","/":"\\/","\b":"\\b","\f":"\\f","\n":"\\n","\r":"\\r","\t":"\\t","\v":"\\u000b"},u=/\uffff/.test("￿")?/[\\\"\x00-\x1f\x7f-\uffff]/g:/[\\\"\x00-\x1f\x7f-\xff]/g
function f(t,e){e.push('"',t.replace(u,(function(t){if(t in c)return c[t]
var e=t.charCodeAt(0),n="\\u"
e<16?n+="000":e<256?n+="00":e<4096&&(n+="0")
return c[t]=n+e.toString(16)})),'"')}var p={scroll:5e3,keydown:5e3,mousemove:5e3,resize:5e3,mousedown:5e3,focus:5e3,pageload:5e3},l={scroll:2e4,keydown:5e3,mousemove:5e3,resize:5e3,mousedown:5e3,focus:5e3,pageload:5e3}
function m(){for(var t="",e=0;e<16;e++)t+=Math.random()
return t}function d(t,e){var n="",i=function(t){t+=String.fromCharCode(128)
for(var e,n,i,a,r,o,s=[1518500249,1859775393,2400959708,3395469782],h=1732584193,c=4023233417,u=2562383102,f=271733878,p=3285377520,l=[],m=Math.ceil((t.length/4+2)/16),d=[m],b=0;b<m;b++){d[b]=[]
for(e=0;e<16;e++)d[b][e]=t.charCodeAt(64*b+4*e)<<24|t.charCodeAt(64*b+4*e+1)<<16|t.charCodeAt(64*b+4*e+2)<<8|t.charCodeAt(64*b+4*e+3)}b=8*(t.length-1)
t=m-1
d[t][14]=Math.floor(b/Math.pow(2,32))
d[t][15]=4294967295&b
for(b=0;b<m;b++){for(o=0;o<16;o++)l[o]=d[b][o]
for(o=16;o<80;o++)l[o]=(l[o-3]^l[o-8]^l[o-14]^l[o-16])<<1|(l[o-3]^l[o-8]^l[o-14]^l[o-16])>>>31
t=h
e=c
n=u
i=f
a=p
for(o=0;o<80;o++)r=(t<<5|t>>>27)+(0==(r=Math.floor(o/20))?e&n^~e&i:1==r?e^n^i:2==r?e&n^e&i^n&i:e^n^i)+a+s[r]+l[o]&4294967295,a=i,i=n,n=e<<30|e>>>2,e=t,t=r
h=h+t&4294967295
c=c+e&4294967295
u=u+n&4294967295
f=f+i&4294967295
p=p+a&4294967295}return[h,c,u,f,p]}(encodeURIComponent(t))
i.splice(e||5,i.length)
P(i,(function(t){if(0==t)t="A"
else{t>>>=0
for(var e="";t>0;)e="ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-".charAt(t%64)+e,t>>>=6
t=e}n+=t}))
return n}function b(t,e,n){var i=Array.prototype.slice,a=i.call(arguments,2)
return function(){return t.apply(e,a.concat(i.call(arguments)))}}function v(t){return void 0!==t}function g(t){return t.replace(/^www\./,"")}var y=/^((https?\:)?(\/\/))/i
function _(t){return t.replace(y,"")}var w=/^((https?\:)?(\/\/))?[^\/]*/
function C(t){return t.replace(w,"")}var I=/\#.*/
function E(t){return t.replace(I,"")}var k=/\?[^\#]*/
function U(t){return t.toLowerCase()}var S=/\/+((\?|\#).*)?$/
function x(t){return t.replace(S,"$1")}function R(t){return t.replace(k,"")}function A(t){var e=t.match(/\?(.*)$/gi)?t.match(/\?(.*)$/gi)[0].slice(1).replace(/#(.*)?/gi,"").split("&"):[],n=t.match(/#(.*)$/gi)?t.match(/#(.*)$/gi)[0]:""
t=t.match(/[#|\?](.*)?/gi)?t.slice(0,t.search(/[#|\?](.*)?/gi)):t,e=function(t,e){var n=[]
P(t,(function(t){e(t)&&n.push(t)}))
return n}(e,(function(t){return 0!==t.search("utm")}))
e.length>0&&(t+="?"+e.join("&"))
return t+n}function j(t,e,n,i){t.addEventListener?t.addEventListener(e,n,!!i):t.attachEvent&&t.attachEvent("on"+e,n)}function D(t,e){var n=r
n.removeEventListener?n.removeEventListener(t,e,a):n.detachEvent&&n.detachEvent("on"+t,e)}function L(t){return"number"==typeof t}function O(t){return"string"==typeof t}function M(t){t=new Date(+t)
return Date.UTC(t.getFullYear(),t.getMonth(),t.getDate())}function T(){return(new Date).getTime()}function F(){return"http:"===r.location.protocol?"http:":"https:"}function N(t){return!!t&&t.constructor===Object}function P(t,e){if(N(t)===n){for(var i in t)if(t.hasOwnProperty(i)&&e(t[i],i)===a)break}else{i=0
for(var r=t.length;i<r&&e(t[i],i)!==a;i++);}}function q(t,e){for(var n=0,i=t.length;n<i;n++)if(e(t[n]))return n
return-1}var B,Y=r.setInterval,H=r.clearInterval,z=r.setTimeout,G=r.clearTimeout
function $(t){switch(t){case e:return"undefined"
case"":return"empty"
default:return t}}function J(t){var e={}
t&&("?"==t.charAt(0)&&(t=t.substring(1)),P((t=t.replace(/\+/g," ")).split(/[&;]/g),(function(t){t=t.split("=")
e[decodeURIComponent(t[0])]=decodeURIComponent(t[1])})))
return e}function X(t,e){var n=""
if(i=r.location.href.match(/[^?]+[?]([^#]+).*/)){var i,a=e||t;(i=J(i[1]))[a]&&(n=i[a])}return encodeURIComponent(n)}function K(t,e){return e?"http:"===t&&"80"===e||"https:"===t&&"443"===e:n}function Q(t){var e={hostname:"",pathname:"",search:"",protocol:"",port:"",hash:""}
if(!t)return e
var n=document.createElement("a"),i=r.location
if(!/^https?:/.test(t)&&0!==t.indexOf("javascript:")&&t.indexOf("app:")<0)if(0===t.indexOf("//"))t=i.protocol+t
else if(0===t.indexOf("/")){var a=K(i.protocol,i.port)?"":i.port
t=i.protocol+"//"+i.hostname+(a?":"+a:"")+t}else{var o=(a=document.baseURI||i.href).indexOf("?");-1===o&&(o=a.indexOf("#"));-1===o&&(o=a.length)
t=-1===(o=a.lastIndexOf("/",o))?"/"+t:a.substr(0,o)+"/"+t}n.href=t
e.hostname=n.hostname
e.pathname=n.pathname
e.search=n.search
e.protocol=n.protocol
e.port=n.port
e.hash=n.hash
"/"!==e.pathname.charAt(0)&&(e.pathname="/"+e.pathname)
""===e.hostname&&(e.hostname=i.hostname)
""===e.protocol&&(e.protocol=i.protocol)
"javascript:"===e.protocol&&(e.pathname="",e.hostname="",e.port="",e.hash="");(K(e.protocol,e.port)||"0"===e.port)&&(e.port="")
return e}function Z(t){var e=t.protocol
t.hostname&&(e+="//"+t.hostname,t.port&&(e+=":"+t.port))
return e+t.pathname+t.search+t.hash}function W(t,e,n,i){e=e||"*"
if("querySelectorAll"in(n=n||document))return n.querySelectorAll(e+"["+t+(i?'="'+i+'"':"")+"]")
for(var a=[],r=(n=(e=n.getElementsByTagName(e)).length,"");n--;)(r=e[n].getAttribute(t))&&(!i||r===i)&&a.push(e[n])
return a}function V(t,n,i){i=i||""
if(t===e)t=a
else{var r;(r=""===i&&t.getAttribute(n))||(r=t.getAttribute(n))&&(r=t.getAttribute(n)===i)
t=r?t:t===document.body?a:V(t.parentNode,n,i)}return t}function tt(t,e,n){t="page"+t+"Offset"
e="scroll"+e
return n&&(n=W("data-cb-scroll-element"))&&n.length?n[0][e]:L(r[t])?r[t]:document.body&&document.body[e]?document.body[e]:document.documentElement[e]?document.documentElement[e]:0}function et(t){var e=(e=document)["CSS1Compat"===e.compatMode?"documentElement":"body"]["client"+t]||0
window["inner"+t]&&(e=Math.min(window["inner"+t],e))
return e}function nt(t){t="scroll"+t
return Math.max(document.body[t],document.documentElement[t])||0}function it(t,e,n){t.ownerDocument||(t=t.correspondingUseElement)
if(!t||!t.ownerDocument)return i
var a=t.ownerDocument.documentElement,r=0,o=v(n)?n+1:-1
O(e)?(e=e.toLowerCase(),n=function(t){return(t=t.nodeName)&&t.toLowerCase()===e}):n=e
for(;t&&t!==a&&r!==o;){if(n(t))return t
t=t.parentNode
r++}return i}function at(t){return t.nodeName&&"a"===t.nodeName.toLowerCase()&&(!t.namespaceURI||"http://www.w3.org/1999/xhtml"===t.namespaceURI)}function rt(t){return(t=t||window.event)?it(t.target||t.srcElement,at,10):i}function ot(t,e){var n=document.createElement(t)
P(e,(function(t,e){n.setAttribute(e,t)}))
return n}function st(){this.G={}
this.bb=1}function ht(t,e,n,i){t.bb++
t.G[e]=t.G[e]||{}
t.G[e][t.bb]=[n,i]
return t.bb}function ct(t,i){if(O(i))t.G[i]=e,delete t.G[i]
else if(L(i)){var r=n
P(t.G,(function(t){P(t,(function(n,o){if(parseInt(o,10)===i)return t[o]=e,delete t[o],r=a}))
return r}))}}st.prototype.P=function(t,e){if(this.G[t]){var n=arguments.length>1?Array.prototype.slice.call(arguments,1):[]
P(this.G[t],(function(t){var e
t&&2===t.length&&(e=t[0],t=t[1],e.apply(t,n))}))}}
st.prototype.addEventListener=function(t,e){var n=ht(this,t,e)
e._cbEventId=n}
st.prototype.removeEventListener=function(t,e){this.G[t]&&this.G[t][e._cbEventId]&&this.G[t][e._cbEventId][0]===e&&ct(this,e._cbEventId)}
var ut,ft,pt,lt,mt,dt=new st,bt={B:function(){bt.Oa?bt.xa("pageload"):(bt.Eb=[{target:r,event:"scroll"},{target:document.body,event:"keydown"},{target:document.body,event:"mousemove"},{target:r,event:"resize"},{target:document.body,event:"mousedown"}],bt.Ea=i,bt.Y=i,bt.Na={},bt.Ma={},bt.pb={},bt.Fa={},P(bt.Eb,(function(t){var e=t.event
j(t.target,e,(function(t){bt.xa.call(bt,e,t)}))})),ht(dt,"f",(function(){bt.xa("focus")})),bt.xa("pageload"),j(document.body,"click",(function(t){(t=rt(t))&&dt.P("c",t)}),n),j(document.body,"contextmenu",(function(t){(t=rt(t))&&dt.P("r",t)})),bt.Oa=n)},Lb:function(){var t=bt.pb.keydown
return t===e?a:(t=T()-t)<=15e3&&t>=0},ja:function(t,e){var n=bt.Fa[t]
if(!n)return""
e=e||T()
var i,a=0
P(n,(function(t){(i=Math.floor((e-t)/1e3))>=0&&i<16&&(a|=1<<i)}))
return"0000"==(n=("0000"+a.toString(16)).slice(-4))?"":n},oc:function(){bt.Fa={}},gb:100,xa:function(t,e){e||(e=window.event)
if(e&&"keydown"===t){var n=e.keyCode?e.keyCode:e.which;(32===n||n>36&&n<41)&&(t="scroll")}bt.wc(t)
bt.Ea===i?bt.zb(t):(!bt.Y||p[bt.Y]<p[t]||l[bt.Y]<l[t])&&(bt.Y=t)},wc:function(t){var e=T()
bt.pb[t]=e
var n=bt.Fa[t]
n?n.length<2?n.push(e):n[n.length-2]>e-1e3?n[n.length-1]=e:n.push(e):n=[e]
n.length>32&&n.shift()
bt.Fa[t]=n},zb:function(t){bt.Ea=z(bt.Qb,bt.gb)
dt.P("a")
bt.Na[t]!==i&&G(bt.Na[t])
bt.Ma[t]!==i&&G(bt.Ma[t])
bt.xb(t,bt.Na,p,"i")
bt.xb(t,bt.Ma,l,"j")},xb:function(t,e,i,r){e[t]=z((function(){G(e[t])
delete e[t]
var i=a
P(e,(function(){i=n
return a}))
i||dt.P(r)}),i[t]+bt.gb)},Qb:function(){G(bt.Ea)
bt.Ea=i
bt.Y&&(bt.zb(bt.Y),bt.Y=i)}}
!function(){var t,n
P(["","moz","o","ms","webkit"],(function(e){t=(e+"Hidden").charAt(0).toLowerCase()+(e+"Hidden").slice(1)
if("boolean"==typeof r.document[t])return n=e,a}))
n!==e&&(lt=t,mt=(n+"VisibilityState").charAt(0).toLowerCase()+(n+"VisibilityState").slice(1),pt=n+"visibilitychange")}()
var vt=a
function gt(){vt=mt&&"prerender"===r.document[mt]?n:a}function yt(){ft=n
dt.P("f")}function _t(){ft=a
dt.P("b")}function wt(t,e,n){r.addEventListener?r.addEventListener(t,n,a):r.document.attachEvent&&r.document.attachEvent(e,n)}function Ct(){var t=n
r.document.hasFocus&&(t=r.document.hasFocus())
var e=a
lt&&(e=r.document[lt])
return t&&!e}function It(){Ct()?yt():_t()}function Et(){this.a=r._sf_async_config||{}
this.kb=b(this.tb,this)}Et.prototype.B=function(){this.ub=0}
Et.prototype.tb=function(){}
Et.prototype.Ba=function(t){if(!vt){var e,n=this.kb
e=new Image(1,1)
n&&(e.onerror=n)
e.src=t}}
Et.prototype.ha=function(){this.kb=i}
var kt="path",Ut="domain",St="useCanonical",xt="useCanonicalDomain",Rt="title",At="virtualReferrer"
function jt(t,e,n){t[e]=t[e]||n}function Dt(t,e){for(var n=r[t]||[];n.length;)e(n.shift())
r[t]={push:e}}function Lt(t){P(document.getElementsByTagName("script"),(function(e){if("string"==typeof e.src&&e.src.match(/chartbeat.js/))return e=J(e.src.split("?")[1]),jt(t,"uid",e.uid),jt(t,Ut,e.domain),a}))}function Ot(t,e){return t[e]?encodeURIComponent(t[e]):""}var Mt={Ob:function(t){try{Mt.create("_cb_test","1",1,t)
var e=Mt.k("_cb_test")
Mt.remove("_cb_test",t)
return"1"===e}catch(t){return a}},k:function(t){t+="="
var e=""
P(document.cookie.split(";"),(function(n){for(;" "===n.charAt(0);)n=n.substring(1,n.length)
if(0===n.indexOf(t))return e=n.substring(t.length,n.length),a}))
return e},create:function(t,e,n,i){var a=r._sf_async_config
if(a&&a.noCookies)return"";(a=new Date).setTime(T()+1e3*n)
t=t+"="+e+"; expires="+a.toGMTString()+"; path="+i
return document.cookie=t},remove:function(t,e){return Mt.k(t)?Mt.create(t,"",-86400,e):""}},Tt={D:function(t){var n=r._sf_async_config
if(!t&&n&&n.noCookies)return i
if(Tt.D.Ja!==e)return Tt.D.Ja
var a,o
t=T()+""
try{if((o=r.localStorage).setItem(t,t),a=o.getItem(t)===t,o.removeItem(t),a)return Tt.D.Ja=o}catch(t){}return Tt.D.Ja=i},k:function(t){var e=Tt.D()
if(!e)return""
var n=e.getItem(t+"_expires")
return n&&(n=+n,!isNaN(n)&&T()>n)?(Tt.remove(t),""):e.getItem(t)||""},create:function(t,e,n){var i=Tt.D()
if(i){var a=new Date
a.setTime(T()+1e3*n)
try{i.setItem(t,e),i.setItem(t+"_expires",a.getTime())}catch(t){}}},remove:function(t){var e=Tt.D()
e&&(e.removeItem(t),e.removeItem(t+"_expires"))}}
function Ft(t,e){this.Aa=t||""
this.Q=e||"/"
this.Rb=Tt.D()!==i||Mt.Ob(this.Q)
this.ab=a
!function(t){if(!Mt.k("_cb_ls")){var e=Tt.D()!==i,a=Mt.k("_SUPERFLY_lockout")
a&&P(["","_v_","_p_"],(function(e){t.create(e+"_SUPERFLY_lockout",a,600,n)}))
var r=Mt.k("_chartbeat3")
r&&(t.create("_v__chartbeat3",r,34128e3,n),Mt.remove("_chartbeat3",t.Q))
e&&((e=Mt.k("_chartbeat2"))&&t.create("_chartbeat2",e,34128e3,n),(e=Mt.k("_chartbeat5"))&&t.create("_chartbeat5",e,60,n))
Mt.create("_cb_ls","1",34128e3,t.Q)}}(this)}(t=Ft.prototype).isSupported=function(){return this.Rb}
t.create=function(t,e,n,i){t=i?t:this.Aa+t;(Tt.D()?Tt:Mt).create(t,e,n,this.Q)
Tt.D()&&Mt.create(t,e,n,this.Q)}
t.update=function(t,e,i,a,r,o,s){t=a?t:this.Aa+t
r=O(r)?r:"::"
a=(a=this.k(t,n))?a.split(r):[]
if(s&&a.length){var h=s(e),c=q(a,(function(t){return s(t)===h}));-1!==c&&a.splice(c,1)}a.push(e)
for(L(o)&&a.length>o&&a.splice(0,a.length-o);a.length>1&&a.join(r).length>4e3;)a.shift()
this.create(t,a.join(r),i,n)}
t.k=function(t,e){t=e?t:this.Aa+t
var i=(Tt.D()?Tt:Mt).k(t)
if(!i&&Tt.D()&&(i=Mt.k(t))&&Mt.k("_cb_ls")){this.ab=n
var a
switch(t){case"_SUPERFLY_lockout":a=600
break
case"_chartbeat4":case"_cb_cp":a=60
break
default:a=34128e3}Tt.create(t,i,a)}return i}
t.remove=function(t,e){t=e?t:this.Aa+t;(Tt.D()?Tt:Mt).remove(t,this.Q)
Tt.D()&&Mt.remove(t,this.Q)}
function Nt(t){var e=i
if(t&&(e=(e=qt())?zt(e.pathname)+e.search+e.hash:e))return e
var n=r.location,a=(e=zt(n.pathname),t=(t=n.search||"").replace(/PHPSESSID=[^&]+/,""),/&utm_[^=]+=[^&]+/gi);(n=a.exec(n.search))&&(t=t.replace(a,""));(n=(a=/\?utm_[^=]+=[^&]+(.*)/i).exec(t))&&(t=t.replace(a,""!=n[1]?"?"+n[1]:""))
return e+t}function Pt(t){return t&&(t=(t=qt())?t.hostname:t)?t:r.location.hostname}function qt(){var t=function(){var t=i
P(document.getElementsByTagName("link"),(function(e){if("canonical"==e.rel)return t=e,a}))
return t}()
return t?Q(t.href):t}for(var Bt={},Yt=0;Yt<81;Yt++)Bt["0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz-._~!$&'()*+,;=:@[]".charCodeAt(Yt)]=n
function Ht(t,e){if("%"===t)return"%25"
var n=parseInt(e,16)
return Bt[n]?String.fromCharCode(n):"%"+e.toUpperCase()}function zt(t){return O(t)?(t=t.replace(/%([0-9A-Fa-f]{2})?/g,Ht)).replace(/[^0-9A-Za-z\-._~!$&'()*+,;=:@\/\[\]?#%]+/g,encodeURIComponent):t}function Gt(t,e){var n=$t()
return v(e)&&!v(n[t])?e:n[t]}function $t(){v(r._cb_shared)||(r._cb_shared={})
return r._cb_shared}var Jt={Hb:{IDLE:0,Gb:1,Fb:2,Ga:3},Ib:{IDLE:0,Gb:1,Fb:2,Ga:3},J:0,M:0,B:function(){Jt.Oa||(ht(dt,"a",Jt.Yb,Jt),ht(dt,"i",Jt.bc,Jt),ht(dt,"f",Jt.$b,Jt),ht(dt,"b",Jt.Zb,Jt),ht(dt,"j",Jt.ac,Jt),Jt.Oa=n)},Vb:function(){return Jt.J},Wb:function(){return Jt.M},Yb:function(){1===Jt.J?Jt.U(3):0===Jt.J&&Jt.U(2)
1===Jt.M?Jt.T(3):0===Jt.M&&Jt.T(2)},bc:function(){3===Jt.J?Jt.U(1):2===Jt.J&&Jt.U(0)},ac:function(){3===Jt.M?Jt.T(1):2===Jt.M&&Jt.T(0)},$b:function(){(0===Jt.J||2===Jt.J)&&Jt.U(3);(0===Jt.M||2===Jt.M)&&Jt.T(3)},Zb:function(){3===Jt.J?Jt.U(2):1===Jt.J&&Jt.U(0)
3===Jt.M?Jt.T(2):1===Jt.M&&Jt.T(0)},U:function(t){Jt.J=t
dt.P("s",t)},T:function(t){Jt.M=t
dt.P("x",t)}}
function Xt(t,n){this.La=t||e
this.Ta=n||e
this.ba=this.O=0
this.nb=b(this.ec,this)
this.$a=this.N=i}(t=Xt.prototype).B=function(){this.ba=this.O=0
this.N=i
this.$a=ht(dt,"s",this.ka,this)
this.ka(Jt.Vb())}
t.ka=function(t){H(this.N)
this.N=i
t===Jt.Hb.Ga&&(this.N=Y(this.nb,1e3))}
t.ec=function(){(this.La===e||this.La())&&(this.O++,this.ba++,this.Ta&&this.Ta())}
t.terminate=function(){H(this.N)
this.N=i
ct(dt,this.$a)}
t.ha=function(){this.terminate()
this.Ta=this.La=e}
function Kt(t,e){Xt.call(this,t,e)}o(Kt,Xt)
Kt.prototype.B=function(){this.ba=this.O=0
this.N=i
this.$a=ht(dt,"x",this.ka,this)
this.ka(Jt.Wb())}
Kt.prototype.ka=function(t){H(this.N)
this.N=i
t===Jt.Ib.Ga&&(this.N=Y(this.nb,1e3))}
function Qt(){Et.call(this)
this.$=[]
this.q=new Ft(this.sc,this.a.cookiePath||"/")
this.q.remove("_SUPERFLY_nosample")
this.F=new Xt
this.Z=new Kt
this.Ua=b(this.za,this)
j(r,"unload",this.Ua)
!function(t){gt()
if(vt){var e=a,i=function(){e||(gt(),vt||(e=n,t(),r.window.setTimeout((function(){r.document.removeEventListener(pt,i,a)}),100)))}
r.document.addEventListener(pt,i,a)}else t()}(b(this.B,this))
this.Pa=a}o(Qt,Et);(t=Qt.prototype).Ya=n
t.B=function(){Qt.X.B.call(this)
this.ua=this.ca=0
this.ga=T()
this.Xa=d(ae(this))
this.Wa=n
this.Qa=72e5
if(this.Ya){var t=+this.a.sessionLength
isNaN(t)||(this.Qa=6e4*t)}if(!(t=Gt("d"))){t=[];(e=this.q.k("_chartbeat2",n)).length>0&&(t=e.split("."))
t.length>5&&(t=[])
var e=T(),i=this.q.k("_cb",n)
i.length>0?t[1]=t[1]||e:i=t[0]
t[0]=""
var o=e-+(t[1]||0),s=e-+(t[2]||0)
$t().n=i&&o>18e5&&s<2592e6?0:1
o=t[4]
if(!(s=s>18e5))if(te(this))s=a
else{var h
s=ne(this),s=oe(s=decodeURIComponent(s))||s
h=re(this)
s=s!==(h=oe(h=decodeURIComponent(h))||h)}o&&!s||(o=d(ae(this)),t[4]=o,this.q.remove("_cb_svref",n))
s="1"
h=t&&+t[2]
o=t&&t[3]
if(t&&h&&o)if(s=Math.abs((M(e)-M(h))/864e5)){s=Math.min(s,16)-1
for(h="";s--;)h+=0
s=(o+h+"1").slice(-16)}else s=o
o=s
i||(i=this.a.utoken||d(ae(this),3),t[1]=e)
t[2]=e
t[3]=o
this.a.utoken=this.ra
this.q.create("_cb",i,34128e3,n)
this.q.create("_chartbeat2",t.join("."),34128e3,n)
t[0]=i
$t().d=t}this.Ic=t.join(".")
var c
i=+t[1]
o=+t[2];(e=t[3])&&i&&o&&(c=(Math.min((Math.abs((M(o)-M(i))/864e5)||0)+1,16,e.length)-1).toString(16),c+=("0000"+parseInt(e,2).toString(16)).slice(-4))
this.mb=c
this.hc=Gt("n",1)
this.ra=t[0]
this.rc=t[4]
this.qc=re(this)
this.q.create("_cb_svref",re(this)||"null",1800,n)
this.F.B()
this.Z.B()
Jt.B()
bt.B()
ut||(ft=Ct(),pt&&r.document.addEventListener&&r.document.addEventListener(pt,It,a),wt("focus","onfocusin",yt),wt("blur","onfocusout",_t),ft&&yt(),ut=n)
this.ma=0
this.Kb=ht(dt,"a",this.jc,this)}
function Zt(t){t.q.k("_SUPERFLY_lockout")||vt||(t.fc?t.Ca():(t.fc=n,r._sf_async_config||r._cbq?t.Ca():(t.ya=b(t.Ca,t),j(r,"load",t.ya))))}t.Ca=function(){this.Va=se()
bt.B()
var t=b(this.na,this)
this.ob=Y(t,15e3)
this.na()}
t.na=function(){var t=this.F.ba
t=this.a.reading&&+this.a.reading||t>0
if(this.ua<this.ca&&!t)this.ua++
else{var n
B===e&&(n=r.navigator.userAgent,B=n.indexOf("AppleWebKit")>0&&n.indexOf("FBIOS")>0);(n=B)&&!t?this.ua++:(t?this.ca=0:Vt(this),this.ua=0,this.$.push(0),this.$.length>18&&this.$.shift(),this.Ya&&T()-this.ga>=this.Qa?this.terminate():this.pa())}}
t.tb=function(){this.$.push(1)
var t=0
P(this.$,(function(e){t+=e}))
t<3?(this.Wa=n,Vt(this)):(this.terminate(),this.q.create("_SUPERFLY_lockout","1",600))}
t.za=function(){}
t.jc=function(){var t=Wt(this)
this.ma=Math.max(this.ma,t)}
function Wt(t){return Math.floor(tt("Y","Top",!!t.a.scrollElement))}function Vt(t){var e=(e=t.ca)?Math.min(2*e,16):1
t.ca=e}t.ta=function(){this.za()
this.terminate()}
t.Ab=function(){this.Pa=n
this.B()
Zt(this)}
function te(t){return t.a[At]?n:ee(t)?a:-1!=(t=document.referrer.indexOf("://"+r.location.hostname+"/"))&&t<9}function ee(t){var e=t.a.referrerOverrideQueryParam,n=""
P(window.location.search.substr(1).split("&"),(function(t){if(2==(t=t.split("=")).length&&t[0]==e&&t[1])return n=decodeURIComponent(t[1]).replace(/\+/g," "),a}))
n&&-1==n.indexOf("::")&&(n="external::"+n)
return n}function ne(t){if(!(t=t.a[At]||ee(t))&&(t=document.referrer||"")&&!/^(android-)?app:/.test(t)){var e=Q(t)
"http:"!==e.protocol&&"https:"!==e.protocol||(e.pathname=zt(e.pathname),t=Z(e))}return encodeURIComponent(t)}function ie(t){t=t.a[Rt].slice(0,100)
return encodeURIComponent(t)}function ae(t){return function(t){var e=r.navigator,n=r.window.screen,i=[e.userAgent,e.platform,(new Date).getTimezoneOffset(),n.width+n.height+n.colorDepth]
P(e.plugins,(function(t){i.push(t.name+t.description+t.filename+t[0].type)}))
e=r.performance
return(i=i.concat([e&&e.now?e.now():"",document.title,r.location.href,T(),m()])).concat(t||[]).join()}(t=[ne(t),nt("Width"),nt("Height")])}function re(t){"null"===(t=t.q.k("_cb_svref",n)||ne(t)||"null")&&(t="")
return t}function oe(t){return(t=t.match(/^https?:\/\/([^\/]*)/))?t[1]:i}function se(){if(!(e=r.performance&&r.performance.timing)||0==e.navigationStart)return-1
var t=e.navigationStart,e=e.loadEventStart
return L(t)&&t?L(e)&&e>t?e-t:T()-t:-1}t.terminate=function(){this.F.terminate()
this.Z.terminate()
ct(dt,this.Kb)
this.ya!==e&&D("load",this.ya)
H(this.ob)
$t().d=e
$t().n=e}
t.ha=function(){this.terminate()
D("unload",this.Ua)
this.Ua=this.ya=this.q=this.$=this.a=i
this.F.ha()
this.F=i
this.Z.ha()
this.Z=i
Qt.X.ha.call(this)}
function he(t,e){var n,a,o={}
r.getComputedStyle?n=r.getComputedStyle(t,i):t.currentStyle?a="currentStyle":t.style&&(a="style")
P(e,(function(e){o[e]=n?n[e]||n.getPropertyValue(e):t[a][e]}))
return o}var ce=/matrix(3d)?\((.*)\)/
function ue(t){var e={x:0,y:0}
if(!O(t=he(t,["transform"]).transform))return e
var n=t.match(ce)
if(!n)return e
var i
t=n[2].split(", ")
v(n[1])?(n=12,i=13):(n=4,i=5)
e.x=parseInt(t[n],10)
e.y=parseInt(t[i],10)
return e}function fe(t){var n,o
if(!(u=Mt.k("_chartbeat6")))return i
if(1===(u=u.split("::")).length)n=u[0].split(","),o=0
else{var s,h=function(){var t;(t=Q(t=(t=r.location.href).replace(/-{2,}/g,"-"))).pathname=zt(t.pathname)
return t}(),c=Z(h)
P(u,(function(t,i){var r=t.split(","),h=function(t,e){if(t===e)return 0
if(0===t.length)return e.length
if(0===e.length)return t.length
for(var n=[],i=0,a=e.length;i<=a;i++)n[i]=[i]
for(var r=0,o=t.length;r<=o;r++)n[0][r]=r
var s,h,c
for(i=1;i<=a;i++)for(r=1;r<=o;r++)h=r-1,c=n[s=i-1][h],e.charAt(s)==t.charAt(h)?n[i][r]=c:(h=n[i][h]+1,s=n[s][r]+1,c+=2,n[i][r]=Math.min(h,s,c))
return n[e.length][t.length]}(c,decodeURIComponent(r[0]))
if(0===h)return n=r,o=i,a;(s===e||h<s)&&(s=h,n=r,o=i)}))}u.splice(o,1)
t="_chartbeat6="+u.join("::")+function(t){var e,n=""
if(!N(t))return n
t.rb&&(e=new Date,e.setTime(e.getTime()+t.rb),n+="; expires="+e.toGMTString())
t.domain&&(n+="; domain="+t.domain)
t.path&&(n+="; path="+t.path)
return n}(t)
document.cookie=t
t=[]
var u=decodeURIComponent(n[0]),f=(h=decodeURIComponent(n[1]),n[2])
n.splice(0,3)
for(var p=n.length/3,l=0;l<p;l++){var m=3*l+2
t.push({Gc:u,origin:h,da:f,fa:m<n.length?n[m]:"",Sb:n[3*l],xc:n[3*l+1]})}return t}function pe(t){var e=t.topStorageDomain,i=(t=t[Ut],r.location.hostname)
return e||(function(t,e){if(t===e)return n
for(var i=e.split("."),r=t.split(".");i.length;){if(0===r.length)return a
if(i.pop()!==r.pop())return a}return n}(i,t)?t:i.replace(/^www\./,""))}function le(t,e,n,i,a){this.Ub=t
this.Tb=e
this.yc=n
this.da=i
this.fa=a}function me(t,e){for(var n,a,r,o,s,h,c=e||document.documentElement,u=[],f=i,p=t;p&&p!==c;){n=p.nodeName.toLowerCase()
a=(f=p).nodeName
if((p=p.parentNode)&&p!==document.documentElement){o=0
for(s=0,h=(r=p.children).length;s<h;s++){if(f===r[s]){n+="["+(1+s-o)+"]"
break}r[s].nodeName!==a&&o++}}u.unshift(n)}return u.join("/")}function de(){this.sc="_t_"
Qt.call(this)}o(de,Qt);(t=de.prototype).B=function(){de.X.B.call(this)
Lt(this.a)
var t=!!this.a[St],e=Pt(!!this.a[xt]&&t)
jt(this.a,"mabServer","mabping.chartbeat.net")
jt(this.a,Rt,document.title)
jt(this.a,Ut,e)
this.a[kt]=this.a[kt]?zt(this.a[kt]):Nt(t)
this.la=g(e)
this.a[Ut]=g(this.a[Ut])
this.vc=pe(this.a)
this.ia=this.va=a
this.lb=[]
var r=this;(t=fe({domain:"."+this.vc,rb:6e4,path:"/"}))!==i&&(this.va=n,P(t,(function(t){r.lb.push(new le(t.origin,t.Sb,t.xc,t.da,t.fa))})))
this.sb=0
this.Da=i
!function(t){for(var e=Gt("m")||[];e.length;)t(e.shift())
t={push:t}
$t().m=t}(b(this.dc,this))}
t.pa=function(){var t,e=this.F.O,i=be(this),a=this
this.va&&P(this.lb,(function(n){t=i+"&x="+n.Tb+"&v="+n.yc+"&ml="+n.da+"&xo="+n.Ub+"&e="+e+"&sl="+n.fa
a.Ba(t)}))
!this.ia&&this.Da&&ve(this,this.Da)
this.ia=n}
t.Ca=function(){this.Va=se()
bt.B()
if(this.va){var t=b(this.na,this)
this.ob=Y(t,500)}this.na()}
t.na=function(){var t
this.ia?((t=this.F.O)-15*this.sb>=15&&(this.pa(),this.sb+=1),t>=45&&this.terminate()):this.pa()}
function be(t){var e=t.a
return F()+"//"+e.mabServer+"/ping/mab?h="+encodeURIComponent(e[Ut])+"&p="+encodeURIComponent(e[kt])+"&d="+encodeURIComponent(t.la)+"&u="+t.ra+"&c="+Math.round((T()-t.ga)/600)/100}t.za=function(){}
t.tc=function(t){t=function(t){var e=t.d,n=i
if(e!==i){var a={}
e.s&&P(e.s,(function(t,e){a[e]="string"==typeof t?{ib:t,fa:""}:{ib:t.chosenVariant,fa:t.specificLocation}}))
n={yb:a,da:e.g,qb:e.m}}return{status:t.s,data:n,code:t.c,message:t.m}}(t)
this.ia?ve(this,t):this.Da=t}
function ve(t,e){var n=be(t),a=e.status,r=e.data
if("s"==a&&r!==i){var o=b(t.Ba,t)
N(r.yb)&&P(r.yb,(function(t,e){o(n+"&x="+e+"&v="+t.ib+"&ml="+r.da+"&sl="+t.fa+"&e=-1")}))
"[object Array]"===Object.prototype.toString.call(r.qb)&&P(r.qb,(function(t){o(n+"&me=3&ml="+r.da+"&x="+t)}))}else"e"==a&&t.Ba(n+"&me="+e.code)}t.dc=function(t,e){for(var n=0,i=arguments.length;n<i;n++){var a=(t=arguments[n]).shift()
"t"===a?this.tc.apply(this,t):"v"===a&&this.pc.apply(this,t)}}
t.ta=function(){$t().m=[]
v(this.cb)&&this.cb()
de.X.ta.call(this)}
t.pc=function(t){this.cb=t}
t.terminate=function(){this.cb=this.Hc=e
this.Da=i
this.ia=this.va=e
de.X.terminate.call(this)}
if(!r.pSUPERFLY_mab){var ge=new de,ye={}
ye.evps=b(ge.ta,ge)
ye.svps=b(ge.Ab,ge)
r.pSUPERFLY_mab=ye
Zt(ge)}var _e,we,Ce
function Ie(t){if("https://chartbeat.com"===t.origin&&0===(t=String(t.data)).indexOf("_cb_hud_version=")){var n=t.substr(16)
Ee()
"NONE"!==n&&(t="https://static.chartbeat.com/js/inpage.js","OLD"!==(n=0===n.indexOf("HUD2.")?n.substr(5):"OLD")&&(t="https://static2.chartbeat.com/frontend_ng/hud/hud-inpage/hud-inpage-"+n+".js"),(n=v(e)?e:{}).src=t,(t=ot("script",n)).setAttribute("type","text/javascript"),n=document.head||document.getElementsByTagName("head")[0],v(e)?e.appendChild(t):n&&n.appendChild(t))}}function Ee(){G(we)
we=e
D("message",Ie)
Ce&&Ce.parentNode&&Ce.parentNode.removeChild(Ce)
Ce=e}function ke(){var t=r._sf_async_config&&r._sf_async_config.domain
if(t&&!_e){_e=n
t="https://chartbeat.com/publishing/hud2/versioninfo/?host="+encodeURIComponent(t)
j(r,"message",Ie)
we=z(Ee,1e4)
var i=v(e)?e:{}
i.src=t;(t=ot("iframe",i)).style.display="none"
v(e)?e.appendChild(t):document.body&&document.body.appendChild(t)
Ce=t}}function Ue(t,n){this.Db=n
this.Cb=t[St]
this.Bb=t[xt]
this.S=t[kt]
this.uc=t[Rt]
this.jb=t[Ut]
this.zc=t[At]
this.hb=(this.H=qt())?this.H.hostname:""
this.sa=this.H?zt(this.H.pathname)+this.H.search+this.H.hash:""
this.wb=Nt(a)
this.mc=Pt(a)
var r,o,s=W("property","meta",i,"og:url")
this.oa=(this.ea=s&&s.length?Q(s[0].content):i)?zt(this.ea.pathname)+this.ea.search+this.ea.hash:""
this.ic=this.ea?this.ea.hostname:""
this.Ka=document.title||"";(s=W("property","meta",i,"og:title"))&&s.length&&(r=s[0].content)
this.wa=r;(r=W("property","meta",i,"twitter:title"))&&r.length&&(o=r[0].content)
this.qa=o
o=!!this.Cb
r=this.Cb!==e
s=!!this.Bb
var h,c=this.Bb!==e,u=!!this.H
h=(h=g(this.hb))===(p=g(this.mc))
var f,p=!!this.oa,l=this.H?this.sa===this.oa:a,m=this.sa===this.wb
f=(f=this.sa)===(b=R(this.wb))
var d,b=!!this.Ka,v=!!this.wa,y=!!this.qa,_=this.Ka===this.wa,w=this.qa?this.Ka===this.qa:a,C=this.wa&&this.qa?this.wa===this.qa:a,I=!!this.uc,E=!!this.S,k=this.S?"/"!==this.S.charAt(0):a,U=this.H?this.S===this.sa:a,S=this.oa?this.S===this.oa:a,x=this.H?this.jb===g(this.hb):a,j=this.oa?this.jb===g(this.ic):a,D=!!this.Db,L=this.Db?a:!!this.zc,O="https:"===F(),M=!!XMLHttpRequest
this.S?d=(d=A(this.S))!==R(d):d=a
o=[o,r,s,c,u,h,p,l,m,f,b,v,y,_,w,C,I,E,k,U,S,x,j,D,L,O,M,d]
r=1
for(c=s=0;c<o.length;c++)s|=o[c]&&r,r<<=1
this.Pb=("00000000"+s.toString(16)).slice(-8)}function Se(){"postMessage"in window&&j(r,"message",b(this.cc,this))
Qt.call(this)
Dt("_cbq",b(this.vb,this))}o(Se,Qt)
Se.prototype.B=function(){Se.X.B.call(this)
var t=this.ra
$t().u=t
t=this.Xa
$t().t=t
this.gc=new Ue(this.a,this.Pa)
this.Ia=i
Lt(this.a)
t=!!this.a[St]
var e=Pt(!!this.a[xt]&&t)
jt(this.a,"pingServer","ping.chartbeat.net")
jt(this.a,Rt,document.title)
jt(this.a,Ut,e)
this.a[kt]=this.a[kt]?zt(this.a[kt]):Nt(t)
this.la=g(e)
this.a[Ut]=g(this.a[Ut])
this.Mb=ht(dt,"c",this.kc,this)
this.Nb=ht(dt,"r",this.lc,this)
this.aa=i}
Se.prototype.Jb=function(t){this.Ia=t}
Se.prototype.za=function(){this.q.update("_chartbeat4",["t="+this.Xa,"E="+this.F.O,"EE="+this.Z.O,"x="+Wt(this),"c="+Math.round((T()-this.ga)/600)/100,"y="+nt("Height"),"w="+et("Height")].join("&"),60,e,e,1)}
var xe,Re,Ae="h,p,u,d,g,g0,g1,g3,g4,n,nc,f,c,x,m,y,o,w,j,R,W,I,E,e,v,r,vp,K,l1,KK,PA,b,A,_c,_m,_x,_y,_z,_s,t,V,z,i,L,tz,l,,sn,C,eS,eM,eD,eK,eR,EE,sv,sr,im".split(",");(t=Se.prototype).pa=function(t){this.ub++
var o={}
o.g=this.a.uid
o.g0=Ot(this.a,"sections")
o.g1=Ot(this.a,"authors")
o.g2=Ot(this.a,"zone")
o.g3=Ot(this.a,"sponsorName")
o.g4=Ot(this.a,"type")
!this.a.noCookies&&this.q.isSupported()?o.n=this.hc:o.nc=1
o.c=Math.round((T()-this.ga)/600)/100
o.E=this.F.O
o.EE=this.Z.O
var c=Wt(this)
this.ma=Math.max(this.ma,c)
o.x=c
o.m=this.ma
o.y=nt("Height")
o.o=nt("Width")
o.w=et("Height")
o.b=this.Va>0?this.Va:""
this.mb&&(o.f=this.mb)
o[""]=function(t){var e={}
P(t,(function(t,n){"_"==n.charAt(0)&&(e[n]=t)}))
return e}(this.a)
o.t=this.Xa
o.V=102
o.tz=(new Date).getTimezoneOffset()
o.sn=this.ub
o.sv=this.rc
o.sr=this.qc
c=this.F.ba
o.h=encodeURIComponent(this.a[Ut])
o.p=encodeURIComponent(this.a[kt])
o.u=this.ra
o.d=encodeURIComponent(this.la)
o.j=Math.round(15e3*(this.ca+2)/1e3)
o.R=0
o.W=0
o.I=0
var u=6e4*o.c+this.ga
o.eD=bt.ja("mousedown",u)
o.eM=bt.ja("mousemove",u)
o.eK=bt.ja("keydown",u)
o.eR=bt.ja("resize",u)
o.eS=bt.ja("scroll",u)
bt.oc()
bt.Lb()?o.W=1:this.a.reading&&+this.a.reading||c>0||o.c<.09?o.R=1:o.I=1
o.e=c
c=te(this)
if(this.Wa){this.Wa=a
c&&(this.aa=function(t){var o=t.q.k("_chartbeat5")
if(!o)return i
var s,h,c=o.split("::"),u=(o=c.length,i),f=Z(je(r.location.href))
P(c,(function(t,r){var o=t.split(","),c=function(t,e){if(t===e)return 0
var n=i
P([U,x,_,C,E,R],(function(i,r){t=i(t)
e=i(e)
if(t===e)return n=r+1,a}))
return n}(f,decodeURIComponent(o[3]))
if(0===c)return s=o,u=r,a
if(c===i)return n;(h===e||c<h)&&(h=c,s=o,u=r)}))
if(u===i)return i
c.splice(u,1)
t.q.create("_chartbeat5",c.join("::"),60);(t=s[5])?(t=t.replace(/%2D/g,"-"),t=decodeURIComponent(t)):t=""
return{left:s[0],top:s[1],path:decodeURIComponent(s[2]),href:decodeURIComponent(s[3]),fb:s[4]||"",eb:"",Ha:s.length>7?s[7]:"",Za:s.length>6?s[6]:"c",Sa:o,Ra:s[9]?s[9]:""}}(this))
o.i=ie(this);(u=this.a.hudTrackable)!==e&&(o.L=u?"1":"0")
this.a.alias&&(o.PA=encodeURIComponent(this.a.alias))}if(c){this.aa?(o.v=encodeURIComponent(this.aa.path),o.K=Le(this.aa),this.aa.Sa>1)&&(o.l1=this.aa.Sa):o.v=ne(this)
this.Pa&&(o.vp=1)}else o.r=ne(this)
c=$(o.v)
$t().v=c
c=$(o.r)
$t().r=c
o.A=this.Ia?this.Ia:""
o._c=X("utm_campaign",this.a.campaignTag)
o._m=X("utm_medium",this.a.mediumTag)
o._x=X("utm_source",this.a.sourceTag)
o._y=X("utm_content",this.a.contentTag)
o._z=X("utm_term",this.a.termTag)
o.im=this.gc.Pb
this.a.idSync?(c=[],h(new s,this.a.idSync,c),c=encodeURIComponent(c.join(""))):c=""
o._s=c
o.z=function(t){var e=[],n=t.q.k("_chartbeat4")
n&&(P(n.split("::"),(function(t){e.push(encodeURIComponent(t))})),t.q.remove("_chartbeat4"))
return e}(this)
o.C=this.a.mobileApp?1:""
o.KK=t?Le(t):""
c=(t=this.q).ab
t.ab=a
o.l=c?1:""
this.F.ba=0
this.Ba(F()+"//"+this.a.pingServer+"/ping?"+function(t){var e=[]
P(Ae,(function(n){var i=t[n]
v(i)&&("[object Array]"===Object.prototype.toString.call(i)?P(i,(function(t){e.push(n+"="+t)})):N(i)?P(i,(function(t,n){e.push(n+"="+t)})):((i+"").length||"r"==n)&&e.push(n+"="+i))}))
e.push("_")
return e.join("&")}(o))}
t.cc=function(t){var e=(r=this.a).playerdomain||this.la
if(_(t.origin)===_(e))if(O(e=t.data)&&0===e.indexOf("cbqpush::"))3==(t=e.split("::")).length&&(0===(t=t.slice(1))[0].indexOf("_")&&this.vb(t))
else if("cbdata?"==e){e="&u="+Gt("u")
var n="&t="+Gt("t"),i="&v="+Gt("v"),a="&r="+Gt("r"),r="domain="+encodeURIComponent(r[Ut])+"&uid="+encodeURIComponent(r.uid)+"&path="+encodeURIComponent(r[kt])+"&title="+ie(this)+"&referrer="+ne(this)+"&internal="+(te(this)?"1":"0")+"&subdomain="+encodeURIComponent(this.la)+e+n+i+a+"&utoken="+this.ra
t.source.postMessage(r,"*")}}
t.vb=function(t){"_demo"===t[0]&&this.a._demo?this.a._demo=this.a._demo+"%2C"+t[1]:this.a[t[0]]=t[1]
this.ca=0}
function je(t){(t=Q(t=t.replace(/-{2,}/g,"-"))).pathname=zt(t.pathname)
return t}t.kc=function(t){De(this,t,"c")}
t.lc=function(t){De(this,t,"r")}
function De(t,i,o){if(t.Ya&&T()-t.ga>=t.Qa)t.terminate()
else{if(0===(h=je(h=i.href||"")).protocol.indexOf("http")){var s=h.hostname!==r.location.hostname,h=Z(h),c=it(i,(function(t){return t.id})),u=me(i,c),f=""
t.a.moduleAttribute&&(f=(f=(f=V(i,t.a.moduleAttribute))?f.getAttribute(t.a.moduleAttribute):"").replace(/::/g,"-").substr(0,40))
c?(u&&(u="/"+u),u="*[@id='"+c.id+"']"+u,c=me(i)):c=u
u=d(u)
c=d(c)
i=function(t,i,r){var o=t.offsetLeft,s=t.offsetTop
o+=(f=ue(t)).x
s+=f.y
for(var h=a,c=r?0:Math.floor(tt("X","Left",e)),u=r?0:Math.floor(tt("Y","Top",e)),f=t.offsetParent;t&&t!==i&&t!==document.body;){t===f&&(f=ue(t),o+=t.offsetLeft+f.x,s+=t.offsetTop+f.y,f=t.offsetParent)
r||(o-=t.scrollLeft,s-=t.scrollTop)
if("fixed"===he(t,["position"]).position){h=n
break}t=t.parentElement}r||(o-=i?i.scrollLeft:c,s-=i?i.scrollTop:u)
h&&(o+=c,s+=u)
return{x:o,y:s}}(i,e,n)
o={left:i.x,top:i.y,path:t.a[kt],href:h,fb:u,Ha:c,eb:"",Za:o,Sa:0,Xb:t.a[Ut],Ra:f}
t.pa(o)
s||t.q.update("_chartbeat5",function(t){var e=encodeURIComponent(t.eb)
e=e.replace(/-/g,"%2D")
e.length>512&&(e="")
return[t.left,t.top,encodeURIComponent(t.path),encodeURIComponent(t.href),t.fb,e,t.Za,t.Ha,encodeURIComponent(t.Xb),t.Ra].join(",")}(o),60,a,e,3,(function(t){return(t=t.split(","))[2]+","+t[3]}))}}}function Le(t){return[t.left,t.top,t.fb,encodeURIComponent(t.eb),t.Za,encodeURIComponent(t.href),t.Ha,t.Ra].join("::")}t.terminate=function(){ct(dt,this.Mb)
ct(dt,this.Nb)
Se.X.terminate.call(this)}
if(!r.pSUPERFLY){var Oe=new Se,Me={}
r.pSUPERFLY=Me
var Te=r.pSUPERFLY_mab,Fe=r.pSUPERFLY_pub,Ne=[]
Te&&Ne.push(Te)
Fe&&(Ne.push(Fe),Fe.addEngagedAdFilter&&(Me.addEngagedAdFilter=Fe.addEngagedAdFilter),Fe.refreshAd&&(Me.refreshAd=Fe.refreshAd),Fe.registerGptSlot&&(Me.registerGptSlot=Fe.registerGptSlot),Dt("_cba",(function(t){t()})))
Me.virtualPage=(xe=function(){Oe.ta()
P(Ne,(function(t){t.evps()}))},Re=function(){Oe.Ab()
P(Ne,(function(t){t.svps()}))},function(t,e){if(!vt){xe()
var n=r._sf_async_config,i="",a=_(a=n[kt]);/^\//.test(a)&&(i=g(r.location.hostname))
n[At]=F()+"//"+i+a
if(O(t))n[kt]=zt(t),e&&(n[Rt]=e)
else if(N(t)){var o=["authors","sections",Rt,kt]
P(t,(function(t,e){-1===q(o,(function(t){return t===e}))&&0!==e.indexOf("_")||(n[e]=e===kt?zt(t):t)}))}Re()}})
Me.activity=b(Oe.Jb,Oe)
Zt(Oe)
var Pe=Tt.D(n)
if(Pe&&Pe.getItem("_cb_ip")){var qe=r.location;/^(.+[.])?chartbeat\.com$/.test(qe.hostname)&&/^\/publishing\/(overlay|hud|mab)\//.test(qe.pathname)||ke()}else j(r,"message",(function t(e){if(/[\/.]chartbeat\.com$/.test(e.origin)){var i=Tt.D(n),a=String(e.data)
i&&0==a.indexOf("_cb_ip")&&(i.setItem("_cb_ip","1"),e.source.postMessage(1,e.origin),ke(),D("message",t))}}))}}()

//# sourceMappingURL=chartbeat.map
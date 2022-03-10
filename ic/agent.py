import time
import cbor2
from waiter import wait
from .candid import decode, Types
from .identity import *
from .constants import *
from .utils import to_request_id
from .certificate import lookup
import hashlib
import re
from termcolor import colored

def sign_request(req, iden):
    req_id = to_request_id(req)
    msg = IC_REQUEST_DOMAIN_SEPARATOR + req_id
    sig = iden.sign(msg)
    envelop = {
        'content': req,
        'sender_pubkey': sig[0],
        'sender_sig': sig[1]
    }
    
    if iden.delegation != None:
        print("Delegation representation independent hash",
              iden.delegation["delegation"],
              hashlib.sha256(to_request_id(iden.delegation["delegation"])).digest().hex())
        print(colored(f"Signing request with delegation", "blue"))
        envelop.update({
            'sender_delegation': [iden.delegation],
        })

        # Need to byte-encode various fields
        envelop["sender_delegation"][0]["signature"] = bytes(envelop["sender_delegation"][0]["signature"])
        envelop["sender_delegation"][0]["delegation"]["pubkey"] = \
            bytes(envelop["sender_delegation"][0]["delegation"]["pubkey"])
        
        print(colored("Sender public key for delegation " + \
                      bytes(iden.delegation_sender_pubkey).hex(), "yellow"))
        print(colored("Sender delegation signature " \
                      + bytes(envelop["sender_delegation"][0]["signature"]).hex(), "yellow"))
        print(colored("Sender delegation signature, decoded cbor: ", "red"),
                      cbor2.loads(bytes(envelop["sender_delegation"][0]["signature"])))
        print(colored("Sender delegation delegation pubkey " \
                      + bytes(envelop["sender_delegation"][0]["delegation"]["pubkey"]).hex(), "yellow"))
        print(colored("sender_sig " \
                      + bytes(sig[1]).hex(), "yellow"))
        print(colored("sender_pubkey " \
                      + bytes(sig[0]).hex(), "yellow"))

    print(colored(envelop, "yellow"))
    print("cbor encoding", colored("evenlop", "red"), envelop)
    
    c = cbor2.dumps(envelop)
    print("cbord encoded", colored("evenlop", "red"), c.hex())
    return req_id, c

# According to did, get the method returned param type
def getType(method:str):
    if method == 'totalSupply':
        return Types.Nat
    elif method == 'name':
        return Types.Text
    elif method == 'balanceOf':
        return Types.Nat
    elif method == 'transfer':
        return Types.Variant({'ok': Types.Nat, 'err': Types.Variant})
    else:
        # pass
        return Types.Nat

class Agent:
    def __init__(self, identity, client, nonce_factory=None, ingress_expiry=300, root_key=IC_ROOT_KEY):
        self.identity = identity
        self.client = client
        self.ingress_expiry = ingress_expiry
        self.root_key = root_key
        self.nonce_factory = nonce_factory

    def get_principal(self):
        return self.identity.sender()

    def get_expiry_date(self):
        return int(time.time() + self.ingress_expiry) * 10**9

    def query_endpoint(self, canister_id, data):
        ret = self.client.query(canister_id, data)
        print("query_endpoint ret", ret)
        try:
            ret_str = ret.decode('utf-8')
            if 'Failed to authenticate' in ret_str:
                print('Failed to authenticate .. analysing string', ret_str)

            m = re.search("signature d9d9[a-z0-9]*", ret_str)
            if m:
                cbor = m[0][len("signature")+1:]
                cbor_decoded = cbor2.loads(bytes.fromhex(cbor))
                print("CBOR ", cbor_decoded)
                print(bytes(cbor_decoded["certificate"]).hex())

                # Certificate is naother CBOR encoded value
                inner_cbor = cbor2.loads(bytes(cbor_decoded["certificate"]))
                print("tree", inner_cbor["tree"][1])
                print("signature", bytes(inner_cbor["signature"]).hex())
                print(inner_cbor.keys())
                
        except (UnicodeDecodeError, AttributeError):
            pass
        return cbor2.loads(ret)

    def call_endpoint(self, canister_id, request_id, data):
        self.client.call(canister_id, request_id, data)
        return request_id

    def read_state_endpoint(self, canister_id, data):
        result = self.client.read_state(canister_id, data)
        return result

    def query_raw(self, canister_id, method_name, *arg):
        assert len(arg) == 1 or len(arg) == 2
        req = {
            'request_type': "query",
            'sender': self.identity.sender().bytes,
            'canister_id': Principal.from_str(canister_id).bytes if isinstance(canister_id, str) else canister_id.bytes,
            'method_name': method_name,
            'arg': arg[0],
            'ingress_expiry': self.get_expiry_date()
        }
        _, data = sign_request(req, self.identity)
        result = self.query_endpoint(canister_id, data)
        print("result in query_raw", result)
        # result in query_raw {'status': 'replied', 'reply': {'arg': b'DIDL\        
        if isinstance(result, dict) and "reply" in result:
            print('candid encoded result, which we decode later', result["reply"]["arg"])
        if result['status'] == 'replied':
            if len(arg) == 1:
                res = decode(result['reply']['arg'])
            else:
                res = decode(result['reply']['arg'], arg[1])
            return res
        elif result['status'] == 'rejected':
            return result['reject_message']

    def update_raw(self, canister_id, method_name, *arg):
        assert len(arg) == 1 or len(arg) == 2
        req = {
            'request_type': "call",
            'sender': self.identity.sender().bytes,
            'canister_id': Principal.from_str(canister_id).bytes if isinstance(canister_id, str) else canister_id.bytes,
            'method_name': method_name,
            'arg': arg[0],
            'ingress_expiry': self.get_expiry_date()
        }
        req_id, data = sign_request(req, self.identity)
        req = self.call_endpoint(canister_id, req_id, data)
        print(colored('update_raw - req', 'blue'), req)
        status, result = self.poll(canister_id, req_id)
        if status != 'replied':
            return  status
        else:
            if len(arg) == 1:
                res = decode(result)
            else:
                res = decode(result, arg[1])
            return res
            

    def read_state_raw(self, canister_id, paths):
        req = {
            'request_type': 'read_state',
            'sender': self.identity.sender().bytes,
            'paths': paths, 
            'ingress_expiry': self.get_expiry_date(),
        }
        _, data = sign_request(req, self.identity)
        ret = self.read_state_endpoint(canister_id, data)
        d = cbor2.loads(ret)
        print(d)
        cert = cbor2.loads(d['certificate'])
        return cert

    def request_status_raw(self, canister_id, req_id):
        paths = [
            ['request_status'.encode(), req_id],
        ]
        cert = self.read_state_raw(canister_id, paths)
        status = lookup(['request_status'.encode(), req_id, 'status'.encode()], cert)
        if (status == None):
            return status, cert
        else:
            return status.decode(), cert

    def poll(self, canister_id, req_id, delay=1, timeout=30):
        status = None
        for _ in wait(delay, timeout):
            status, cert = self.request_status_raw(canister_id, req_id)
            if status == 'replied' or status == 'done' or status  == 'rejected':
                break
        
        if status == 'replied':
            path = ['request_status'.encode(), req_id, 'reply'.encode()]
            res = lookup(path, cert)
            return status, res
        else:
            return status, _

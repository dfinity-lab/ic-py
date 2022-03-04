import hashlib

from ecdsa.curves import Ed25519, SECP256k1
from .principal import Principal
import ecdsa

from termcolor import colored

class Identity:
    def __init__(self, privkey = "", type = "ed25519", anonymous = False):
        privkey = bytes(bytearray.fromhex(privkey))
        self.anonymous = anonymous
        if anonymous:
            return
        self.key_type = type
        if type == 'secp256k1':
            if len(privkey) > 0:
                self.sk = ecdsa.SigningKey.from_string(privkey, curve=ecdsa.SECP256k1, hashfunc=hashlib.sha256)
            else:
                self.sk = ecdsa.SigningKey.generate(curve=ecdsa.SECP256k1, hashfunc=hashlib.sha256)
            self._privkey = self.sk.to_string().hex()
            self.vk = self.sk.get_verifying_key()
            self._pubkey = self.vk.to_string().hex()
            self._der_pubkey = self.vk.to_der()
        elif type == 'ed25519':
            if len(privkey) > 0:
                self.sk = ecdsa.SigningKey.from_string(privkey, curve=ecdsa.Ed25519)
            else:
                self.sk = ecdsa.SigningKey.generate(curve=ecdsa.Ed25519)
            self._privkey = self.sk.to_string().hex()
            self.vk = self.sk.get_verifying_key()
            self._pubkey = self.vk.to_string().hex()
            self._der_pubkey = self.vk.to_der()
        else:
            raise 'unsupported identity type'

        self.delegation = None
        self.delegation_principal = None
        self.session_key = None
        self.delegation_sender_pubkey = None

    @staticmethod
    def from_pem(pem: str):
        key = ecdsa.SigningKey.from_pem(pem)
        privkey = key.to_string().hex()
        type = "unknown"
        if key.curve == Ed25519:
            type = 'ed25519'
        elif key.curve == SECP256k1:
            type = 'secp256k1'
        return Identity(privkey=privkey, type=type)

    def to_pem(self):
        pem = self.sk.to_pem(format="pkcs8")
        return pem

    def sender(self):
        if self.anonymous:
            return Principal.anonymous()
        elif self.delegation:
            principal = self.delegation_principal
            print(colored(f"Returning sender {principal} for delegation", "blue"))
            return principal
        return Principal.self_authenticating(self._der_pubkey)

    def add_delegation(self, delegation, delegation_principal, session_key, delegation_sender_pubkey):
        self.delegation = delegation
        self.delegation_principal = delegation_principal
        self.session_key = session_key
        self.delegation_sender_pubkey = delegation_sender_pubkey

    def sign(self, msg: bytes):
        if self.anonymous:
            return (None, None)
        if self.session_key:
            print(colored(f"Using session key {self.session_key} to sign message", "blue"))
            sig = self.session_key.sign(msg)
            return (bytes(self.delegation_sender_pubkey), sig)
        if self.key_type == 'ed25519':
            sig = self.sk.sign(msg)
            return (self._der_pubkey, sig)
        elif self.key_type == 'secp256k1':
            sig = self.sk.sign(msg)
            return (self._der_pubkey, sig)

    @property
    def privkey(self):
        return self._privkey

    @property
    def pubkey(self):
        return self._pubkey

    @property
    def der_pubkey(self):
        return self._der_pubkey

    def __repr__(self):
        return "Identity(" + self.key_type + ', ' + self._privkey + ", " + self._pubkey + ")"

    def __str__(self):
        return "(" + self.key_type + ', ' + self._privkey + ", " + self._pubkey + ")"

from enum import Enum

class RequestType(str, Enum):
    """Every Request will have a prefix, to determine the request type
    """
    UNKNOWN = 'UNKNOWN'
    PUB_KEY_SEQUENCE = 'PUB_KEY_SEQUENCE'
    CIPHERTEXT_SEQUENCE = 'CIPHERTEXT_SEQUENCE'
    SEND_MESSAGE_REQUEST = 'SEND_MESSAGE_REQUEST'
    CONNECT_WITH_CONTACT_REQUEST = 'CONNECT_WITH_CONTACT_REQUEST'
    ASSIGN_UUID_AND_SEED = 'ASSIGN_UUID_AND_SEED'
    CONNECT_WITH_CONTACT_RESPONSE = 'CONNECT_WITH_CONTACT_RESPONSE'
    NEW_ACCOUNT_REQUEST = 'NEW_ACCOUNT_REQUEST'
    LOGIN_REQUEST = 'LOGIN_REQUEST'

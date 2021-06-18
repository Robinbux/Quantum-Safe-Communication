from socket import AF_INET, socket, SOCK_STREAM
from threading import Thread
import ssl
from dataclasses import dataclass
import logging
import json
import uuid
from util.oqs_utils import RequestType
import base64
import sqlite3
from util.security_util import generate_random_seed_phrase
import sys

@dataclass(eq=True, frozen=True)
class ClientKeyPair:
    client: socket
    client_public_key: bytes
    client_name: str
    client_id: uuid.UUID


logging.basicConfig(
    format="[%(asctime)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S"
)

def dict_factory(cursor, row):
    d = {}
    for idx, col in enumerate(cursor.description):
        d[col[0]] = row[idx]
    return d

class OQSServer():
    def __init__(self, host: str = 'localhost', port: int = 33000, bufsize: int = 50000):
        self.__logger = logging.getLogger(__name__)
        self.__logger.setLevel(logging.DEBUG)
        self.__host = host
        self.__port = port
        self.__address = (host, port)
        self.__bufsize = bufsize

        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(
            certfile='../pqca/server/falcon512_srv.crt',
            keyfile='../pqca/server/falcon512_srv.key')

        self.__server = socket(AF_INET, SOCK_STREAM, 0)
        self.__server.bind(self.__address)
        self.__server = context.wrap_socket(self.__server, server_side=True)
        self.__clients = []

        # DB
        self.__setup_db()

    def __setup_db(self):
        self.__logger.info("Setting up Database...")
        self.__connection = sqlite3.connect("server/pq-chat-server.db", check_same_thread=False)
        self.__connection.row_factory = sqlite3.Row
        self.__cursor = self.__connection.cursor()

        setup_file = open("server/setup-server.sql")
        setup_file_str = setup_file.read()
        self.__cursor.executescript(setup_file_str)
        self.__connection.commit()

    def __accept_connections(self):
        while True:
            client, client_address = self.__server.accept()
            self.__logger.info(f"Client with address \"{client_address[0]}:{client_address[1]}\" has "
                               f"connected")
            Thread(target=self.__handle_client, args=(client,)).start()

    def __handle_client(self, client):
        client_key_pair = None
        while True:
            msg = client.recv(self.__bufsize)

            request_json = json.loads(msg.decode())
            request_type_str = request_json['requestType']
            print(f"REQUEST TYPE STRING: {request_type_str}")
            request_type = RequestType[request_type_str]
            print(f"REQUEST TYPE: {request_type}")
            print(type(request_type))

            if request_type == RequestType.NEW_ACCOUNT_REQUEST:
                client_key_pair = self.__handle_new_account(request_json, client)

            elif request_type == RequestType.LOGIN_REQUEST:
                client_key_pair = self.__login_client(request_json, client)

            elif request_type == RequestType.CONNECT_WITH_CONTACT_REQUEST:
                self.__connect_with_contact(request_json['contactUUID'], client)

            elif request_type == RequestType.SEND_MESSAGE_REQUEST:
                self.__send_message_to_contact(request_json, client_key_pair)

    def __login_client(self, request_json, client):
        db_client = self.__db_client_with_uuid(request_json['UUID'])

        client_key_pair = ClientKeyPair(
            client=client,
            client_public_key=db_client['public_key'],
            client_name=db_client['name'],
            client_id=db_client['uuid']
        )
        self.__clients.append(client_key_pair)
        return client_key_pair

    def __db_client_with_uuid(self, uuid: str):
        return self.__cursor.execute("""
            SELECT c.* FROM clients c WHERE uuid = :uuid
                              """, {"uuid": uuid}).fetchone()
        
    def __client_key_pair_with_uuid(self, uuid:str):
        return next((contact for contact in self.__clients if str(contact.client_id) == uuid), None)


    def __handle_new_account(self, request_json, client):
        print("RECEIVED NEW ACCOUNT")
        # Generate random UUID for client
        client_uuid = uuid.uuid4()

        client_key_pair = ClientKeyPair(
            client=client,
            client_public_key=base64.b64decode(request_json['publicKey']),
            client_name=request_json['name'],
            client_id=client_uuid
        )
        self.__clients.append(client_key_pair)

        # Generate Seed Phrase
        seed_phrase, seed_phrase_hash = generate_random_seed_phrase()

        # Safe in DB
        self.__cursor.execute("""
            INSERT INTO clients 
            VALUES (
                :uuid, 
                :name, 
                :publicKey
            ) 
        """, {
            "uuid": str(client_uuid),
            "name": request_json['name'],
            "publicKey": base64.b64decode(request_json['publicKey']),
        })
        self.__connection.commit()

        print("---SENDING UUID AND SEED---")
        payload = {}
        payload['requestType'] = RequestType.ASSIGN_UUID_AND_SEED
        payload['UUID'] = str(client_uuid)
        payload['seedPhrase'] = seed_phrase
        payload['seedHash'] = base64.b64encode(seed_phrase_hash).decode('ascii')
        print(f"PAYLOAD: {payload}")
        json_data = json.dumps(payload)
        client.send(json_data.encode())
        return client_key_pair

    def __send_message_to_contact(self, request_json, sender_client_key_pair):
        """Sends message to specified contact

        Args:
            contact_uuid (str): UUID of contact that receives the message
            msg (bytes): Message to send, with a SEND_MESSAGE prefix
        """
        contact_client_key_pair = self.__client_key_pair_with_uuid(request_json['contactUUID'])
        
        request_json['senderUUID'] = str(sender_client_key_pair.client_id)
        request_json['senderName'] = sender_client_key_pair.client_name
        request_json['senderPublicKey'] = base64.b64encode(sender_client_key_pair.client_public_key).decode('ascii')

        json_data = json.dumps(request_json)
        self.__broadcast_raw(contact_client_key_pair.client, json_data.encode())

    def __broadcast_raw(self, client, msg):
        client.send(msg)

    def __connect_with_contact(self, contact_uuid: str, client):
        """Checks if the client can connect with contact

        Args:
            contact_uuid (str): UUID of contact to connect with

        Returns:
            bool: True if contact exists, False otherwise
        """
        contact = self.__db_client_with_uuid(contact_uuid)
        contact_exists = contact is not None
        print(f"Contact with UUID {contact_uuid} exists: {contact_exists}")

        payload = {}
        payload['requestType'] = RequestType.CONNECT_WITH_CONTACT_RESPONSE
        payload['contactExists'] = contact_exists
        if contact_exists:
            print(f"CONTACT: {contact}")
            payload['contactUUID'] = contact_uuid
            payload['contactName'] = contact['name']
            # To send pub key, encode Bytes to ascii via Base64
            payload['contactPublicKey'] = base64.b64encode(contact['public_key']).decode('ascii')
        print(f"Payload: {payload}")

        json_data = json.dumps(payload)

        self.__broadcast_raw(client, json_data.encode())

    def start(self, num_connections: int = 5):

        self.__logger.info(f"Starting server. Listening to max {num_connections} connections")
        self.__server.listen(num_connections)

        print("Waiting for connection...")
        thread = Thread(target=self.__accept_connections)
        thread.start()
        thread.join()

    def close(self):
        sys.exit()

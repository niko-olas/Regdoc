"""Invia un messaggio di prova sul topic `documents`, per provare consumer e dead-letter.

Uso, con il venv di src/audit:
    src\\audit\\.venv\\Scripts\\python.exe infra\\scripts\\send_test_message.py <namespace> <tipo>

Tipi:
    valid     messaggio ben formato, come quelli della Function
    invalid   corpo non JSON: il consumer lo manda in dead-letter in modo esplicito

Il messaggio arriva a TUTTE le subscription del topic, anche a `indexer`.
Richiede il ruolo "Azure Service Bus Data Sender" sul namespace o sul topic.
"""
import json
import sys
import uuid

from azure.identity import DefaultAzureCredential
from azure.servicebus import ServiceBusClient, ServiceBusMessage

TOPIC = "documents"


def build(kind: str) -> ServiceBusMessage:
    message_id = f"test-{uuid.uuid4()}"
    if kind == "valid":
        body = json.dumps({
            "event_id": message_id,
            "domain": "stufe-pellet",
            "manufacturer": "test",
            "model": "test",
            "doc_type": "test",
            "blob_path": "stufe-pellet/test/test/test/messaggio-di-prova.pdf",
            "attributes": {},
        })
        return ServiceBusMessage(body, content_type="application/json", message_id=message_id)
    if kind == "invalid":
        return ServiceBusMessage("questo non è JSON", content_type="text/plain", message_id=message_id)
    sys.exit(f"tipo sconosciuto: {kind}\n\n{__doc__}")


def main() -> None:
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    namespace, kind = sys.argv[1], sys.argv[2]
    message = build(kind)

    client = ServiceBusClient(f"{namespace}.servicebus.windows.net", credential=DefaultAzureCredential())
    with client, client.get_topic_sender(TOPIC) as sender:
        sender.send_messages(message)
    print(f"Inviato messaggio '{kind}' con MessageId {message.message_id}")


if __name__ == "__main__":
    main()

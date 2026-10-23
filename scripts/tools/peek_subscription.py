"""Mostra i messaggi di una subscription senza consumarli (peek).

Uso, dalla radice con il venv di sviluppo:
    .venv\\Scripts\\python.exe scripts\\tools\\peek_subscription.py <namespace> [subscription] [--dlq]

Richiede il ruolo "Azure Service Bus Data Receiver" sul namespace.
"""
import json
import sys

from azure.identity import DefaultAzureCredential
from azure.servicebus import ServiceBusClient, ServiceBusSubQueue

TOPIC = "documents"


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        sys.exit(__doc__)
    namespace = args[0]
    subscription = args[1] if len(args) > 1 else "indexer"
    sub_queue = ServiceBusSubQueue.DEAD_LETTER if "--dlq" in sys.argv else None

    client = ServiceBusClient(f"{namespace}.servicebus.windows.net", credential=DefaultAzureCredential())
    with client, client.get_subscription_receiver(TOPIC, subscription, sub_queue=sub_queue) as receiver:
        # peek: legge senza lock e senza incrementare il delivery count.
        # Il messaggio resta disponibile per il consumatore vero.
        messages = receiver.peek_messages(max_message_count=20)
        where = f"{TOPIC}/{subscription}" + (" (dead-letter)" if sub_queue else "")
        print(f"{len(messages)} messaggi in {where}\n")
        for m in messages:
            print(f"MessageId:      {m.message_id}")
            print(f"Enqueued:       {m.enqueued_time_utc}")
            print(f"DeliveryCount:  {m.delivery_count}")
            print(f"Properties:     {m.application_properties}")
            if sub_queue:
                print(f"DLQ reason:     {m.dead_letter_reason} — {m.dead_letter_error_description}")
            print("Body:")
            try:
                print(json.dumps(json.loads(str(m)), indent=2, ensure_ascii=False))
            except json.JSONDecodeError:
                print(str(m))  # i messaggi in dead-letter possono non essere JSON
            print("-" * 60)


if __name__ == "__main__":
    main()

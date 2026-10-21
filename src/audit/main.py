"""Consumer della subscription `audit`: registra ogni messaggio, nessuna logica di dominio.

Avvio locale, dalla cartella src/:
    python -m audit.main
"""
import logging
import os
import signal

from azure.identity import DefaultAzureCredential
from azure.servicebus import ServiceBusClient, ServiceBusReceivedMessage, ServiceBusReceiver, ServiceBusReceiveMode

from audit.messages import InvalidMessage, parse_body, summarize

logger = logging.getLogger("regdoc.audit")
_running = True


def _stop(*_) -> None:
    global _running
    _running = False


def _setup_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    # I log AMQP dell'SDK a livello INFO sono molto verbosi.
    logging.getLogger("azure").setLevel(logging.WARNING)

    if os.getenv("APPLICATIONINSIGHTS_CONNECTION_STRING"):
        from azure.monitor.opentelemetry import configure_azure_monitor

        # Solo i logger "regdoc.*" vengono esportati ad Application Insights:
        # i campi passati con extra= diventano customDimensions interrogabili in KQL.
        configure_azure_monitor(logger_name="regdoc")


def _handle(receiver: ServiceBusReceiver, msg: ServiceBusReceivedMessage, simulate_failure: bool) -> None:
    try:
        body = parse_body(str(msg))
        if simulate_failure:
            raise RuntimeError("guasto simulato (AUDIT_SIMULATE_FAILURE=1)")

        fields = summarize(body) | {"message_id": msg.message_id, "delivery_count": msg.delivery_count}
        logger.info(
            "Documento %s (%s) message_id=%s delivery_count=%d",
            fields["blob_path"], fields["domain"], msg.message_id, msg.delivery_count,
            extra=fields,
        )
        receiver.complete_message(msg)

    except InvalidMessage as exc:
        # Errore permanente: riprovare non cambierebbe l'esito. Dead-letter esplicito con
        # un motivo leggibile, invece di consumare i tentativi fino a max delivery count.
        logger.warning("Messaggio %s in dead-letter: %s", msg.message_id, exc)
        receiver.dead_letter_message(msg, reason="InvalidMessage", error_description=str(exc))

    except Exception:
        # Errore imprevisto, potenzialmente transitorio: abandon rilascia subito il lock e il
        # messaggio torna disponibile con DeliveryCount + 1. Superato il max delivery count
        # della subscription (3 per audit), è Service Bus a spostarlo in dead-letter.
        logger.exception("Elaborazione fallita per %s (delivery_count=%d), abandon", msg.message_id, msg.delivery_count)
        receiver.abandon_message(msg)


def main() -> None:
    _setup_logging()
    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)  # inviato da Container Apps quando ferma una replica

    topic = os.getenv("SERVICEBUS_TOPIC", "documents")
    subscription = os.getenv("SERVICEBUS_SUBSCRIPTION", "audit")
    simulate_failure = os.getenv("AUDIT_SIMULATE_FAILURE") == "1"

    client = ServiceBusClient(os.environ["SERVICEBUS_FQDN"], credential=DefaultAzureCredential())
    # PEEK_LOCK: il messaggio viene cancellato solo dopo complete_message. Se il processo
    # muore a metà, il lock scade e il messaggio torna disponibile: nessuna perdita.
    receiver = client.get_subscription_receiver(
        topic_name=topic, subscription_name=subscription, receive_mode=ServiceBusReceiveMode.PEEK_LOCK
    )
    with client, receiver:
        logger.info("In ascolto su %s/%s (guasto simulato: %s)", topic, subscription, simulate_failure)
        while _running:
            for msg in receiver.receive_messages(max_message_count=10, max_wait_time=5):
                _handle(receiver, msg, simulate_failure)
    logger.info("Arresto completato")


if __name__ == "__main__":
    main()

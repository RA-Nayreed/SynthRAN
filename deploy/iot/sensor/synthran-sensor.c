#include "contiki.h"
#include "mqtt.h"
#include "net/ipv6/uip.h"
#include "net/ipv6/uip-ds6.h"
#include "net/routing/routing.h"
#include "sys/etimer.h"
#include "sys/log.h"

#include <stdio.h>
#include <string.h>

#include "experiment-generated.h"

#define LOG_MODULE "synthran-sensor"
#define LOG_LEVEL LOG_LEVEL_INFO

#define BROKER_PORT 1883
#define MQTT_SEGMENT_SIZE 128
#define PAYLOAD_SIZE 256
#define TOPIC_SIZE 128
#define CLIENT_ID_SIZE 24
#define RETRY_PERIOD (2 * CLOCK_SECOND)
#define PUBLISH_PERIOD (SYNTHRAN_SENSOR_PERIOD_SECONDS * CLOCK_SECOND)

PROCESS(synthran_sensor_process, "SynthRAN deterministic MQTT sensor");
AUTOSTART_PROCESSES(&synthran_sensor_process);

static struct mqtt_connection connection;
static struct etimer timer;
static char client_id[CLIENT_ID_SIZE];
static char topic[TOPIC_SIZE];
static char payload[PAYLOAD_SIZE];
static uint32_t sequence;
static uint8_t connected;

static uint8_t
sensor_number(void)
{
  uint8_t value = linkaddr_node_addr.u8[LINKADDR_SIZE - 1];
  if(value < 1 || value > 10) {
    return 0;
  }
  return value;
}

static int
have_connectivity(void)
{
  return uip_ds6_get_global(ADDR_PREFERRED) != NULL &&
         uip_ds6_defrt_choose() != NULL;
}

static void
mqtt_event(struct mqtt_connection *m, mqtt_event_t event, void *data)
{
  (void)m;
  (void)data;

  switch(event) {
  case MQTT_EVENT_CONNECTED:
    connected = 1;
    LOG_INFO("mqtt connected\n");
    process_poll(&synthran_sensor_process);
    break;
  case MQTT_EVENT_DISCONNECTED:
  case MQTT_EVENT_CONNECTION_REFUSED_ERROR:
    connected = 0;
    LOG_WARN("mqtt disconnected\n");
    process_poll(&synthran_sensor_process);
    break;
  default:
    break;
  }
}

static void
connect_broker(void)
{
  if(!have_connectivity()) {
    return;
  }

  mqtt_connect(&connection,
               SYNTHRAN_EDGE_BROKER_IPV6,
               BROKER_PORT,
               SYNTHRAN_SENSOR_PERIOD_SECONDS * 3,
               MQTT_CLEAN_SESSION_ON);
}

static void
publish_event(void)
{
  uint8_t number = sensor_number();
  int payload_len;

  if(number == 0 || !connected || !mqtt_ready(&connection)) {
    return;
  }

  sequence++;
  payload_len = snprintf(
    payload,
    sizeof(payload),
    "{\"schema\":\"synthran/telemetry/v1alpha1\","
    "\"run_id\":\"%s\","
    "\"sensor_id\":\"sensor-%02u\","
    "\"sequence\":%lu,"
    "\"sensor_time_ms\":%lu,"
    "\"value_milli\":%ld}",
    SYNTHRAN_RUN_ID,
    number,
    (unsigned long)sequence,
    (unsigned long)(clock_time() * 1000UL / CLOCK_SECOND),
    (long)(number * 1000L + (sequence % 1000UL))
  );

  if(payload_len <= 0 || payload_len >= (int)sizeof(payload)) {
    LOG_ERR("payload overflow\n");
    return;
  }

  mqtt_publish(&connection,
               NULL,
               topic,
               (uint8_t *)payload,
               (uint16_t)payload_len,
               MQTT_QOS_LEVEL_0,
               MQTT_RETAIN_OFF);

  LOG_INFO("published sensor-%02u seq=%lu\n",
           number,
           (unsigned long)sequence);
}

PROCESS_THREAD(synthran_sensor_process, ev, data)
{
  uint8_t number;

  PROCESS_BEGIN();

  number = sensor_number();
  if(number == 0) {
    LOG_ERR("mote id must map to sensor 01..10\n");
    PROCESS_EXIT();
  }

  snprintf(client_id, sizeof(client_id), "synthran-sensor-%02u", number);
  snprintf(topic, sizeof(topic),
           "%s/%s/sensor/sensor-%02u",
           SYNTHRAN_TOPIC_PREFIX, SYNTHRAN_RUN_ID, number);

  mqtt_register(&connection,
                &synthran_sensor_process,
                client_id,
                mqtt_event,
                MQTT_SEGMENT_SIZE);
  connection.auto_reconnect = 0;

  etimer_set(&timer, RETRY_PERIOD);

  while(1) {
    PROCESS_YIELD();

    if(ev == PROCESS_EVENT_POLL) {
      if(connected) {
        etimer_set(&timer, PUBLISH_PERIOD);
      } else {
        etimer_set(&timer, RETRY_PERIOD);
      }
    }

    if(ev == PROCESS_EVENT_TIMER && data == &timer) {
      if(!connected) {
        connect_broker();
        etimer_set(&timer, RETRY_PERIOD);
      } else if(connection.out_buffer_sent) {
        publish_event();
        etimer_set(&timer, PUBLISH_PERIOD);
      } else {
        etimer_set(&timer, CLOCK_SECOND);
      }
    }
  }

  PROCESS_END();
}

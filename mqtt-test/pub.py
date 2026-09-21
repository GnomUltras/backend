import paho.mqtt.client as mqtt
from paho.mqtt.enums import CallbackAPIVersion

client = mqtt.Client(CallbackAPIVersion.VERSION2)
client.connect("127.0.0.1", 1883, 60)

# Sendet direkt von Windows an Windows-Port 1883
client.publish("station/started", '{"team_id": "Team-01", "status": "started"}')
client.disconnect()
print("Gesendet!")
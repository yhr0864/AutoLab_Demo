start "nats-js-server-1" cmd /k "nats-server -c .\jsnode1.conf" 

start "nats-js-server-2" cmd /k "nats-server -c .\jsnode2.conf" 

start "nats-js-server-3" cmd /k "nats-server -c .\jsnode3.conf" 
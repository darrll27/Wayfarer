from multiprocessing import Process
import os
import argparse
import tempfile
import yaml
from mission_api import load_yaml, run_group_process


def main(config=None):
	"""Launch missions.

	`config` may be either:
	  - a path string to a YAML config file, or
	  - a dict containing the already-loaded config.

	For multiprocessing we write a short-lived temp file only when a dict was
	provided (so worker processes can load the config by path). The temp file
	is created in the system temp dir (not inside the repo) and removed after
	processes finish.
	"""
	# resolve config (path or dict)
	tmp_cfg_file = None
	if isinstance(config, dict):
		cfg_dict = config
		# write a short-lived temp file for worker processes to consume
		fd, tmp_cfg_file = tempfile.mkstemp(prefix="pathfinder-config-", suffix=".yaml")
		os.close(fd)
		with open(tmp_cfg_file, "w") as fh:
			yaml.safe_dump(cfg_dict, fh)
		config_path = tmp_cfg_file
	else:
		config_path = config or os.environ.get("PATHFINDER_CONFIG") or os.path.join(os.path.dirname(__file__), "pathfinder.config.yaml")
		cfg_dict = load_yaml(config_path) or {}

	# Derive MQTT config from pathfinder config if present, else use defaults
	mqtt_cfg = cfg_dict.get("mqtt", {
		"host": "localhost",
		"port": 1883,
		"client_id": "pathfinder-controller",
		"topic_prefix": "wayfarer/v1",
		"qos": 0
	})
	topic_prefix = mqtt_cfg.get("topic_prefix", "wayfarer/v1")

	processes = []
	try:
		for group_name in cfg_dict.get('groups', {}).keys():
			# pass config path so each process constructs its own Pathfinder instance
			p = Process(target=run_group_process, args=(config_path, group_name))
			p.start()
			processes.append(p)

		# Monitor processes
		for p in processes:
			p.join()
		print("All group missions completed.")
	finally:
		if tmp_cfg_file:
			try:
				os.remove(tmp_cfg_file)
			except Exception:
				pass


if __name__ == "__main__":
	parser = argparse.ArgumentParser(prog="pathfinder-launch", description="Launch missions defined in pathfinder.config.yaml")
	parser.add_argument("--config", "-c", help="Path to pathfinder config YAML file to use")
	parser.add_argument("--host", help="Override MQTT host")
	parser.add_argument("--port", type=int, help="Override MQTT port")
	parser.add_argument("--client-id", help="Override MQTT client id")
	parser.add_argument("--topic-prefix", help="Override MQTT topic prefix")
	parser.add_argument("--qos", type=int, choices=[0,1,2], help="Override MQTT qos")
	args = parser.parse_args()

	# If MQTT overrides were supplied, build an in-memory effective config
	cli_overrides = {k: v for k, v in {
		"host": args.host,
		"port": args.port,
		"client_id": args.client_id,
		"topic_prefix": args.topic_prefix,
		"qos": args.qos,
	}.items() if v is not None}

	cfg_path = args.config or os.path.join(os.path.dirname(__file__), "pathfinder.config.yaml")
	if cli_overrides:
		# load base config and merge
		base_cfg = load_yaml(cfg_path) or {}
		base_cfg.setdefault("mqtt", {})
		base_cfg["mqtt"].update(cli_overrides)
		main(config=base_cfg)
	else:
		main(config=cfg_path)
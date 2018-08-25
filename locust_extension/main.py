import datetime
import importlib
import json
import logging
import socket
import sys
import time
from pathlib import Path

import gevent
import yaml as yaml
from locust import web, runners, events
from locust.inspectlocust import print_task_ratio, get_task_ratio_dict
from locust.log import setup_logging, console_logger
from locust.main import parse_options, version, find_locustfile, load_locustfile
from locust.runners import LocalLocustRunner, MasterLocustRunner, SlaveLocustRunner
from locust.stats import stats_printer, stats_writer, print_error_report, write_stat_csvs, print_stats, \
    print_percentile_stats

import os
from .informative_runner import ParameterizableLocustRunner

logger = logging.getLogger("locust-flying-locust_extension")


def main(user_params=None, common_param=None):
    parser, options, arguments = parse_options()

    # setup logging
    setup_logging(options.loglevel, options.logfile)
    logger = logging.getLogger(__name__)

    if options.show_version:
        print("Locust %s" % (version,))
        sys.exit(0)

    locustfile = find_locustfile(options.locustfile)

    if not locustfile:
        logger.error(
            "Could not find any locustfile! Ensure file ends in '.py' and see --help for available options.")
        sys.exit(1)

    if locustfile == "locust.py":
        logger.error("The locustfile must not be named `locust.py`. Please rename the file and try again.")
        sys.exit(1)

    docstring, locusts = load_locustfile(locustfile)

    if options.list_commands:
        console_logger.info("Available Locusts:")
        for name in locusts:
            console_logger.info("    " + name)
        sys.exit(0)

    if not locusts:
        logger.error("No Locust class found!")
        sys.exit(1)

    # make sure specified Locust exists
    if arguments:
        missing = set(arguments) - set(locusts.keys())
        if missing:
            logger.error("Unknown Locust(s): %s\n" % (", ".join(missing)))
            sys.exit(1)
        else:
            names = set(arguments) & set(locusts.keys())
            locust_classes = [locusts[n] for n in names]
    else:
        # list() call is needed to consume the dict_view object in Python 3
        locust_classes = list(locusts.values())

    if options.show_task_ratio:
        console_logger.info("\n Task ratio per locust class")
        console_logger.info("-" * 80)
        print_task_ratio(locust_classes)
        console_logger.info("\n Total task ratio")
        console_logger.info("-" * 80)
        print_task_ratio(locust_classes, total=True)
        sys.exit(0)
    if options.show_task_ratio_json:
        from json import dumps
        task_data = {
            "per_class": get_task_ratio_dict(locust_classes),
            "total": get_task_ratio_dict(locust_classes, total=True)
        }
        console_logger.info(dumps(task_data))
        sys.exit(0)

    if not options.no_web and not options.slave:
        # spawn web greenlet
        logger.info("Starting web monitor at %s:%s" % (options.web_host or "*", options.port))
        main_greenlet = gevent.spawn(web.start, locust_classes, options)


    if not options.master and not options.slave:
        if user_params:
            runners.locust_runner = ParameterizableLocustRunner(locust_classes, options, user_params, common_param)
        else:
            runners.locust_runner = LocalLocustRunner(locust_classes, options)
        # spawn client spawning/hatching greenlet
        if options.no_web:
            runners.locust_runner.start_hatching(wait=True)
            main_greenlet = runners.locust_runner.greenlet
    elif options.master:
        runners.locust_runner = MasterLocustRunner(locust_classes, options)
        if options.no_web:
            while len(runners.locust_runner.clients.ready) < options.expect_slaves:
                logging.info("Waiting for slaves to be ready, %s of %s connected",
                             len(runners.locust_runner.clients.ready), options.expect_slaves)
                time.sleep(1)

            runners.locust_runner.start_hatching(options.num_clients, options.hatch_rate)
            main_greenlet = runners.locust_runner.greenlet
    elif options.slave:
        try:
            runners.locust_runner = SlaveLocustRunner(locust_classes, options)
            main_greenlet = runners.locust_runner.greenlet
        except socket.error as e:
            logger.error("Failed to connect to the Locust master: %s", e)
            sys.exit(-1)

    if not options.only_summary and (options.print_stats or (options.no_web and not options.slave)):
        # spawn stats printing greenlet
        gevent.spawn(stats_printer)

    if options.csvfilebase:
        gevent.spawn(stats_writer, options.csvfilebase)

    def shutdown(code=0):
        """
        Shut down locust by firing quitting event, printing/writing stats and exiting
        """
        logger.info("Shutting down (exit code %s), bye." % code)

        events.quitting.fire()
        print_stats(runners.locust_runner.request_stats)
        print_percentile_stats(runners.locust_runner.request_stats)
        if options.csvfilebase:
            write_stat_csvs(options.csvfilebase)
        print_error_report()
        sys.exit(code)

    # install SIGTERM handler
    def sig_term_handler():
        logger.info("Got SIGTERM signal")
        shutdown(0)

    gevent.signal(gevent.signal.SIGTERM, sig_term_handler)

    try:
        logger.info("Starting Locust %s" % version)
        main_greenlet.join()
        code = 0
        if len(runners.locust_runner.errors):
            code = 1
        shutdown(code=code)
    except KeyboardInterrupt as e:
        shutdown(0)

def put_into_argv(locust_params):
    current_time = datetime.datetime.now().strftime(".%Y%m%d%H%M%S")
    for key, value in locust_params.items():
        if key not in ["no-web"]:
            sys.argv.append("--" + key)
            locust_log_file = value

            if key in ["csv", "logfile"]:
                locust_log_file += current_time
                Path(locust_log_file).parent.mkdir(parents=True, exist_ok=True)

            sys.argv.append(str(locust_log_file))
        else:
            if value:
                sys.argv.append("--" + key)

class PreprocessError(RuntimeError):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)



if __name__ == '__main__':
    # sys.stdin.flush()
    # time.sleep(1)

    logger.info("loading config form %s", sys.argv[1])
    config = yaml.load(Path(sys.argv[1]).open(encoding="utf-8"))
    del sys.argv[1]

    before_module = importlib.import_module(config["test_process"]["before"])
    after_module = importlib.import_module(config["test_process"]["after"])
    custom_config_parser = importlib.import_module(config["custom_config_parser"])
    try:
        logger.info("processing before test....")
        before_module.run(config)
    except Exception as e:
        logger.info(e)
        raise PreprocessError(e)

    locust_params = config["locust"]
    put_into_argv(locust_params)

    custom_config = config["custom"]

    user_params, common_param = custom_config_parser.parse(locust_params, custom_config)

    logger.info("test start....")
    main(user_params, common_param)
    logger.info("test finish....")

    try:
        logger.info("processing after test....")
        after_module.run(config)
    except Exception as e:
        logger.info(e)
        raise PreprocessError(e)
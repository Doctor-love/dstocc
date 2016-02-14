#!/usr/bin/env python
# vim: tabstop=8 expandtab shiftwidth=4 softtabstop=4

'''dstocc - Loads dirsearch JSON output and captures result with CutyCapt'''

developers = ['Joel Rangsmo <joel@rangsmo.se>']
description = __doc__
version = '0.1'
license = 'GPLv2'

try:
    import json
    import time
    import string
    import argparse
    import subprocess
    import logging as log

    from Queue import Queue
    from random import shuffle
    from threading import Thread

    # PyInstaller requires explicit import of exit
    from sys import exit

except ImportError as missing:
    print(
        'UNKNOWN - Could not import all required modules: "%s".\n' % missing +
        'The script requires Python 2.7 or 2.6 with the "argparse" module\n'
        'Installation with PIP: "pip install argparse"')

    exit(3)

# -----------------------------------------------------------------------------

def split_status_codes(status_code_string):
    '''Split a comma separated string with status codes into a list'''
    
    status_codes = status_code_string.split(',')

    try:
        status_codes = map(int, status_codes)

    except:
        raise argparse.ArgumentTypeError('Status codes must to be integers')

    return status_codes


def parse_args():
    '''Parses commandline arguments provided by the user'''

    parser = argparse.ArgumentParser(
        description=description,
        epilog=(
            'Developed by %s - licensed under %s!'
            % (', '.join(developers), license)))

    parser.add_argument(
        '-f', '--file', dest='results_file',
        help='Path to dirsearch JSON output file',
        metavar='/path/to/results.json', type=argparse.FileType('r'),
        required=True)

    parser.add_argument(
        '-i', '--include', dest='included_codes',
        help='HTTP status codes to include in CutyCapt (default: All)',
        metavar='"200,500"', type=split_status_codes, default=[])

    parser.add_argument(
        '-e', '--exclude', dest='excluded_codes',
        help='HTTP status codes to exclude in CutyCapt (default: None)',
        metavar='"403,404"', type=split_status_codes, default=[])

    parser.add_argument(
        '-c', '--command-template',
        help='Template for CutyCapt shell command (default: %(default)s)',
        metavar='CMD', type=str,
        default=(
            'CutyCapt --url=%URL% --out=%FILENAME% '
            '--min-width=1024 --min-height=768'))

    parser.add_argument(
        '-t', '--timeout',
        help='Timeout in seconds for CutyCapt execution (default: 20)',
        metavar='SECONDS', type=int, default=20)

    parser.add_argument(
        '-T', '--threads', dest='worker_threads',
        help='Number of threads for CutyCapt workers (default: 4)',
        metavar='INT', type=int, default=4)

    parser.add_argument(
        '-V', '--verbose', dest='log_verbose',
        help='Enable verbose application logging',
        action='store_true', default=False)

    parser.add_argument(
        '-v', '--version',
        help='Display script version',
        action='version', version=version)

    return parser.parse_args()

# -----------------------------------------------------------------------------

def load_target_urls(results_file, included_codes, excluded_codes):
    '''Loads JSON results file and filters out URLs that should be CutyCaped'''

    log.debug('Loading resuls from JSON file')

    # Strips leading NULL characters and loads JSON from the results file
    results_string = results_file.read()

    results_string = results_string[results_string.index('{'):]
    results = json.loads(results_string)

    log.debug('dirsearch result data: "%s"' % str(results))

    # Filters the sub-paths that should be captured
    target_urls = []

    for url in results.iterkeys():
        log.debug('Checking sub-paths for URL "%s"' % url)

        sub_paths = results[url]

        for sub_path in sub_paths:
            log.debug('Checking sub-path "%s" for URL "%s"' % (sub_path, url))

            status_code = sub_path['status']
            path = sub_path['path']

            if status_code in excluded_codes:
                log.debug('Status code %s should be excluded' % status_code)

                continue

            elif not included_codes or status_code in included_codes:
                log.debug('Including status code %s' % status_code)

                target_urls.append(url + path)

    # Shuffels the target list array to spread out the capturing load
    shuffle(target_urls)

    log.debug('Target URLs for capturing: "%s"' % target_urls)

    return target_urls

# -----------------------------------------------------------------------------

def cutycapt_exec(url, command_template, timeout):
    '''Executes the CutyCapt application with subprocess to target URL'''

    log.info('Capturing URL "%s"...' % url)

    # Creates a "safe" filename for output image
    safe_chars = string.letters + string.digits + '-_.='

    file_name = url.replace('/', '_')
    file_name = file_name.replace(':', '-')
    file_name = filter(lambda char: char in safe_chars, file_name)
    file_name += '.png'

    log.debug('Generated filename for URL "%s": "%s"' % (url, file_name))

    # -------------------------------------------------------------------------
    log.debug('Building command string from template "%s"' % command_template)

    command = command_template.replace('%URL%', url)
    command = command.replace('%FILENAME%', file_name)

    log.debug('Executing shell command "%s"' % command)

    shell_exec = subprocess.Popen(
        command.split(' '),
        stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    # Poll the execution status of command every 10 milliseconds
    attempts = timeout * 10

    while shell_exec.poll() is None and attempts:
        attempts -= 1
        time.sleep(0.1)

    if not attempts:
        log.error(
            'Failed to capture "%s": Execution timed out after %i seconds'
            % (url, timeout))

        log.debug('Terminating process "%i"' % shell_exec.pid)
        shell_exec.terminate()

        return

    output = shell_exec.communicate()
    exit_code = shell_exec.returncode

    log.debug(
        'Execution status for URL "%s" - output: "%s", exit code "%i"'
        % (url, output, exit_code))

    if exit_code != 0:
        log.error(
            'Failed to execute CutyCapt for URL "%s": "%s"' % (url, output))

        return
    
    # -------------------------------------------------------------------------
    log.info('Saving capture of URL "%s" to "%s"' % (url, file_name))

    return


def cutycapt_worker(worker_id, queue, command_template, timeout):
    '''Loads URLs from queue and runs the CutyCapt execution function'''

    log.debug('Starting CutyCap worker %i' % worker_id)

    while True:
        log.debug('Loading new URL from queue in worker %i' % worker_id) 

        url = queue.get()

        # Captures the URL with CutyCapt
        cutycapt_exec(url, command_template, timeout)

        queue.task_done()

# -----------------------------------------------------------------------------

def main():
    '''Main application function'''

    # Parses commandline arguments
    args = parse_args() 

    # Sets up application logging
    if args.log_verbose:
        log.basicConfig(level=log.DEBUG, format='%(levelname)s: %(message)s')

    else:
        log.basicConfig(level=log.INFO, format='%(levelname)s: %(message)s')

    log.debug('Script has been started with arguments: "%s"' % str(args))

    # Loads results file and extracts a list of URL to CutyCapt 
    try:
        urls = load_target_urls(
            args.results_file, args.included_codes, args.excluded_codes)

    except Exception as error_msg:
        log.error('Failed to load result file: "%s"' % error_msg)

        exit(1)

    if len(urls):
        log.info('Capturing %i URLs with CutyCapt' % len(urls))

    else:
        log.error('No URLs in the result file matched filtering requirements')

        exit(1)

    # -------------------------------------------------------------------------
    log.debug('Populating queue with URLs')

    queue = Queue()

    for url in urls:
        queue.put(url)

    log.debug('Starting %i CutyCapt worker threads' % args.worker_threads)

    for worker_id in range(args.worker_threads):
        worker = Thread(
            target=cutycapt_worker,
            args=(worker_id, queue, args.command_template, args.timeout))

        worker.setDaemon(True)
        worker.start()

    # -------------------------------------------------------------------------
    while not queue.empty():
        log.info('URLs still in queue for capturing: %i' % queue.qsize())

        time.sleep(3)

    log.info('Waiting for all URLs to be handled by capturing workers')
    queue.join()

    log.info('Finished capturing %i URLs!' % len(urls))

    exit(0)


if __name__ == '__main__':
    # Protects the script output from unhandled exceptions
    try:
        main()

    except SystemExit as exit_code:
        exit(int(str(exit_code)))

    except KeyboardInterrupt:
        print('\ndstocc was interrupted by keyboard - exiting!')

        exit(3)

    except Exception as error_msg:
        print('Script generated unhandled exception: "%s"' % error_msg)

        exit(1)

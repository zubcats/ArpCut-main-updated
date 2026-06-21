from tools.license_remote_signin import license_transient_reason


def test_license_transient_reason_dns():
    raw = (
        'Could not reach license server (HTTPSConnectionPool(host='
        "'zubcut-license-signin.zubcats.workers.dev', port=443): "
        'Max retries exceeded with url: /validate (Caused by NameResolutionError('
        '"HTTPSConnection(host=\'zubcut-license-signin.zubcats.workers.dev\', port=443): '
        "Failed to resolve 'zubcut-license-signin.zubcats.workers.dev' "
        '([Errno 11001] getaddrinfo failed)"))).'
    )
    assert license_transient_reason(raw) == (
        'Offline — cannot resolve license server (check internet/DNS). Will retry.'
    )


def test_license_transient_reason_timeout():
    assert license_transient_reason('Connection timed out after 12s') == (
        'License server timed out. Will retry.'
    )

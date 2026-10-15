# V3.90 Release Notes

V3.90 closes the application-level Testnet egress boundary required by Master Prompt M25.

The credentialed Testnet transport now binds every outbound REST request to the exact
Testnet host, requires HTTPS, rejects non-default ports and embedded userinfo, blocks
ambient proxy configuration, disables implicit proxy use in the stdlib opener, and
rejects HTTP redirects before a request can move to another endpoint.

The boundary is injectable and fully offline-testable. No exchange mutation is
performed during V3.90 verification.

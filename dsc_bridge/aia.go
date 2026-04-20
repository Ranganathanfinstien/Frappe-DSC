package main

import (
	"crypto/sha1"
	"crypto/x509"
	"encoding/base64"
	"fmt"
	"io"
	"net/http"
	"time"
)

const aiaHTTPTimeout = 10 * time.Second

// FetchCertChain follows the AIA (Authority Information Access) issuers
// in the leaf certificate to build the chain up to (but not including) the root.
// Returns a slice of DER-encoded intermediate certificates.
func FetchCertChain(leafDER []byte) ([][]byte, error) {
	leaf, err := x509.ParseCertificate(leafDER)
	if err != nil {
		return nil, fmt.Errorf("parsing leaf cert: %w", err)
	}

	var chain [][]byte
	current := leaf

	// Walk up the chain, max 5 levels to prevent loops
	for i := 0; i < 5; i++ {
		if len(current.IssuingCertificateURL) == 0 {
			break
		}

		// Self-signed = root, stop here
		if current.Subject.String() == current.Issuer.String() {
			break
		}

		issuerDER, err := fetchDER(current.IssuingCertificateURL[0])
		if err != nil {
			// Chain may be partial — return what we have
			break
		}

		chain = append(chain, issuerDER)

		issuer, err := x509.ParseCertificate(issuerDER)
		if err != nil {
			break
		}

		current = issuer
	}

	return chain, nil
}

// FetchOCSP fetches an OCSP response for the given certificate from its AIA OCSP URL.
// Returns the raw OCSP response bytes.
func FetchOCSP(certDER []byte, issuerDER []byte) ([]byte, error) {
	cert, err := x509.ParseCertificate(certDER)
	if err != nil {
		return nil, fmt.Errorf("parsing cert: %w", err)
	}

	if len(cert.OCSPServer) == 0 {
		return nil, fmt.Errorf("no OCSP server URL in certificate")
	}

	issuer, err := x509.ParseCertificate(issuerDER)
	if err != nil {
		return nil, fmt.Errorf("parsing issuer cert: %w", err)
	}

	// Build OCSP request
	ocspReqBytes, err := buildOCSPRequest(cert, issuer)
	if err != nil {
		return nil, fmt.Errorf("building OCSP request: %w", err)
	}

	// POST OCSP request to responder
	ocspURL := cert.OCSPServer[0]

	client := &http.Client{Timeout: aiaHTTPTimeout}
	resp, err := client.Post(ocspURL, "application/ocsp-request", bytesReader(ocspReqBytes))
	if err != nil {
		return nil, fmt.Errorf("OCSP request failed: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("OCSP responder returned status %d", resp.StatusCode)
	}

	ocspResp, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, fmt.Errorf("reading OCSP response: %w", err)
	}

	return ocspResp, nil
}

// EncodeCertChainB64 converts a slice of DER certs to base64 strings.
func EncodeCertChainB64(chain [][]byte) []string {
	result := make([]string, len(chain))
	for i, der := range chain {
		result[i] = base64.StdEncoding.EncodeToString(der)
	}
	return result
}

// fetchDER downloads a DER-encoded certificate from a URL.
func fetchDER(url string) ([]byte, error) {
	client := &http.Client{Timeout: aiaHTTPTimeout}
	resp, err := client.Get(url)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("HTTP %d from %s", resp.StatusCode, url)
	}

	return io.ReadAll(resp.Body)
}

// buildOCSPRequest creates a minimal DER-encoded OCSP request.
// Uses SHA-1 hash of issuer name and key as per RFC 6960.
func buildOCSPRequest(cert, issuer *x509.Certificate) ([]byte, error) {
	// We use golang.org/x/crypto/ocsp if available, but for minimal deps
	// we build a simple OCSP request manually.
	//
	// For MVP, we use a GET request with base64-encoded request in URL.
	// Most OCSP responders support this.

	// Import ocsp package would be ideal, but to keep deps minimal,
	// we construct it from the cert serial + issuer hash.
	// This is a simplified implementation.

	// SHA-1 OID: 1.3.14.3.2.26
	sha1OID := []byte{0x06, 0x05, 0x2b, 0x0e, 0x03, 0x02, 0x1a}

	// Hash issuer name and public key with SHA-1
	issuerNameHash := sha1Hash(cert.RawIssuer)
	issuerKeyHash := sha1Hash(issuer.RawSubjectPublicKeyInfo)

	serial := cert.SerialNumber.Bytes()

	// Build CertID
	certID := asn1Sequence(
		asn1Sequence(sha1OID, asn1Null()),             // hashAlgorithm
		asn1OctetString(issuerNameHash),                // issuerNameHash
		asn1OctetString(issuerKeyHash),                 // issuerKeyHash
		asn1Integer(serial),                            // serialNumber
	)

	// Build Request
	request := asn1Sequence(certID)

	// Build TBSRequest
	tbsRequest := asn1Sequence(
		asn1SequenceOf(request), // requestList
	)

	// Build OCSPRequest
	ocspRequest := asn1Sequence(tbsRequest)

	return ocspRequest, nil
}

// --- ASN.1 helpers for OCSP request construction ---

func asn1Sequence(items ...[]byte) []byte {
	return asn1Wrap(0x30, items...)
}

func asn1SequenceOf(items ...[]byte) []byte {
	return asn1Wrap(0x30, items...)
}

func asn1OctetString(data []byte) []byte {
	return asn1Wrap(0x04, data)
}

func asn1Integer(data []byte) []byte {
	// Ensure positive integer (add leading zero if high bit set)
	if len(data) > 0 && data[0]&0x80 != 0 {
		data = append([]byte{0x00}, data...)
	}
	return asn1Wrap(0x02, data)
}

func asn1Null() []byte {
	return []byte{0x05, 0x00}
}

func asn1Wrap(tag byte, contents ...[]byte) []byte {
	var body []byte
	for _, c := range contents {
		body = append(body, c...)
	}

	length := len(body)
	var header []byte

	if length < 128 {
		header = []byte{tag, byte(length)}
	} else if length < 256 {
		header = []byte{tag, 0x81, byte(length)}
	} else {
		header = []byte{tag, 0x82, byte(length >> 8), byte(length)}
	}

	return append(header, body...)
}

func sha1Hash(data []byte) []byte {
	h := sha1.Sum(data)
	return h[:]
}

// bytesReader wraps a byte slice as an io.Reader.
func bytesReader(b []byte) io.Reader {
	return &byteSliceReader{data: b}
}

type byteSliceReader struct {
	data []byte
	pos  int
}

func (r *byteSliceReader) Read(p []byte) (int, error) {
	if r.pos >= len(r.data) {
		return 0, io.EOF
	}
	n := copy(p, r.data[r.pos:])
	r.pos += n
	return n, nil
}

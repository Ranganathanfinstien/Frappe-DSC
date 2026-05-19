package main

import (
	"crypto/sha256"
	"crypto/x509"
	"encoding/base64"
	"encoding/hex"
	"fmt"
	"log"
	"os"
	"sync"

	"github.com/miekg/pkcs11"
)

// TokenInfo describes a detected USB token slot.
type TokenInfo struct {
	Label  string `json:"label"`
	Serial string `json:"serial"`
	Slot   uint   `json:"slot"`
}

// CertInfo describes a certificate found on a token.
type CertInfo struct {
	FingerprintSHA256 string   `json:"fingerprint_sha256"`
	SubjectCN         string   `json:"subject_cn"`
	SubjectFull       string   `json:"subject_full"`
	IssuerCN          string   `json:"issuer_cn"`
	Serial            string   `json:"serial"`
	NotBefore         string   `json:"not_before"`
	NotAfter          string   `json:"not_after"`
	KeyUsage          []string `json:"key_usage"`
	Slot              uint     `json:"slot"`
	TokenSerial       string   `json:"token_serial"`
	CertDERBase64     string   `json:"cert_der_b64"` // base64-encoded raw DER cert
	derBytes          []byte   `json:"-"`            // raw DER, kept for internal signing use
}

// PKCS11Handler manages PKCS#11 library loading and token operations.
type PKCS11Handler struct {
	mu          sync.Mutex
	loadedLibs  []string
	contexts    map[string]*pkcs11.Ctx // lib path -> context
}

// NewPKCS11Handler creates a handler and attempts to load known PKCS#11 libraries.
func NewPKCS11Handler(libPaths []string) *PKCS11Handler {
	h := &PKCS11Handler{
		contexts: make(map[string]*pkcs11.Ctx),
	}

	for _, libPath := range libPaths {
		if _, err := os.Stat(libPath); err != nil {
			continue // library not installed at this path
		}
		log.Printf("pkcs11: found candidate %s, attempting load", libPath)

		ctx := pkcs11.New(libPath)
		if ctx == nil {
			log.Printf("pkcs11: pkcs11.New returned nil for %s (likely missing dependency DLL or wrong architecture)", libPath)
			continue
		}

		if err := ctx.Initialize(); err != nil {
			log.Printf("pkcs11: failed to initialize %s: %v", libPath, err)
			ctx.Destroy()
			continue
		}

		h.contexts[libPath] = ctx
		h.loadedLibs = append(h.loadedLibs, libPath)
		log.Printf("pkcs11: loaded %s", libPath)
	}
	log.Printf("pkcs11: %d library/libraries loaded out of %d candidate paths", len(h.loadedLibs), len(libPaths))

	return h
}

// LoadedLibs returns the list of successfully loaded PKCS#11 libraries.
func (h *PKCS11Handler) LoadedLibs() []string {
	return h.loadedLibs
}

// DetectTokens returns info about all slots with tokens present.
func (h *PKCS11Handler) DetectTokens() []TokenInfo {
	h.mu.Lock()
	defer h.mu.Unlock()

	var tokens []TokenInfo

	for _, ctx := range h.contexts {
		slots, err := ctx.GetSlotList(true) // tokenPresent = true
		if err != nil {
			continue
		}

		for _, slot := range slots {
			info, err := ctx.GetTokenInfo(slot)
			if err != nil {
				continue
			}

			tokens = append(tokens, TokenInfo{
				Label:  info.Label,
				Serial: info.SerialNumber,
				Slot:   slot,
			})
		}
	}

	return tokens
}

// EnumerateCerts lists all certificates on all detected tokens. No PIN required.
func (h *PKCS11Handler) EnumerateCerts() ([]CertInfo, error) {
	h.mu.Lock()
	defer h.mu.Unlock()

	var certs []CertInfo

	for _, ctx := range h.contexts {
		slots, err := ctx.GetSlotList(true)
		if err != nil {
			continue
		}

		for _, slot := range slots {
			tokenInfo, err := ctx.GetTokenInfo(slot)
			if err != nil {
				continue
			}

			session, err := ctx.OpenSession(slot, pkcs11.CKF_SERIAL_SESSION)
			if err != nil {
				continue
			}

			slotCerts, err := h.readCertsFromSession(ctx, session, slot, tokenInfo.SerialNumber)
			if err == nil {
				certs = append(certs, slotCerts...)
			}

			ctx.CloseSession(session)
		}
	}

	return certs, nil
}

func (h *PKCS11Handler) readCertsFromSession(ctx *pkcs11.Ctx, session pkcs11.SessionHandle, slot uint, tokenSerial string) ([]CertInfo, error) {
	// Find certificate objects
	template := []*pkcs11.Attribute{
		pkcs11.NewAttribute(pkcs11.CKA_CLASS, pkcs11.CKO_CERTIFICATE),
	}

	if err := ctx.FindObjectsInit(session, template); err != nil {
		return nil, err
	}
	defer ctx.FindObjectsFinal(session)

	var certs []CertInfo

	for {
		objs, _, err := ctx.FindObjects(session, 10)
		if err != nil || len(objs) == 0 {
			break
		}

		for _, obj := range objs {
			attrs, err := ctx.GetAttributeValue(session, obj, []*pkcs11.Attribute{
				pkcs11.NewAttribute(pkcs11.CKA_VALUE, nil),
			})
			if err != nil || len(attrs) == 0 {
				continue
			}

			certDER := attrs[0].Value
			if len(certDER) == 0 {
				continue
			}

			parsed, err := x509.ParseCertificate(certDER)
			if err != nil {
				continue
			}

			fp := sha256.Sum256(certDER)

			ci := CertInfo{
				FingerprintSHA256: hex.EncodeToString(fp[:]),
				SubjectCN:         parsed.Subject.CommonName,
				SubjectFull:       parsed.Subject.String(),
				IssuerCN:          parsed.Issuer.CommonName,
				Serial:            parsed.SerialNumber.Text(16),
				NotBefore:         parsed.NotBefore.UTC().Format("2006-01-02T15:04:05Z"),
				NotAfter:          parsed.NotAfter.UTC().Format("2006-01-02T15:04:05Z"),
				KeyUsage:          parseKeyUsage(parsed.KeyUsage),
				Slot:              slot,
				TokenSerial:       tokenSerial,
				CertDERBase64:     base64.StdEncoding.EncodeToString(certDER),
				derBytes:          certDER,
			}

			certs = append(certs, ci)
		}
	}

	return certs, nil
}

// FindCertByFingerprint searches all tokens for a cert matching the given SHA-256 fingerprint.
// Returns the cert info, the PKCS#11 context, and the slot.
func (h *PKCS11Handler) FindCertByFingerprint(fingerprint string) (*CertInfo, *pkcs11.Ctx, uint, error) {
	h.mu.Lock()
	defer h.mu.Unlock()

	for _, ctx := range h.contexts {
		slots, err := ctx.GetSlotList(true)
		if err != nil {
			continue
		}

		for _, slot := range slots {
			tokenInfo, _ := ctx.GetTokenInfo(slot)

			session, err := ctx.OpenSession(slot, pkcs11.CKF_SERIAL_SESSION)
			if err != nil {
				continue
			}

			certs, err := h.readCertsFromSession(ctx, session, slot, tokenInfo.SerialNumber)
			ctx.CloseSession(session)
			if err != nil {
				continue
			}

			for _, cert := range certs {
				if cert.FingerprintSHA256 == fingerprint {
					return &cert, ctx, slot, nil
				}
			}
		}
	}

	return nil, nil, 0, fmt.Errorf("certificate with fingerprint %s not found", fingerprint)
}

// SignHash signs a hash using the private key corresponding to the cert with the given fingerprint.
// This triggers the token's native PIN dialog via C_Login.
func (h *PKCS11Handler) SignHash(ctx *pkcs11.Ctx, slot uint, fingerprint string, hashBytes []byte, pin string) ([]byte, []byte, error) {
	session, err := ctx.OpenSession(slot, pkcs11.CKF_SERIAL_SESSION|pkcs11.CKF_RW_SESSION)
	if err != nil {
		return nil, nil, fmt.Errorf("opening session: %w", err)
	}
	defer ctx.CloseSession(session)

	// Login with PIN
	if err := ctx.Login(session, pkcs11.CKU_USER, pin); err != nil {
		return nil, nil, fmt.Errorf("login: %w", err)
	}
	defer ctx.Logout(session)

	// Find the private key
	privKeyTemplate := []*pkcs11.Attribute{
		pkcs11.NewAttribute(pkcs11.CKA_CLASS, pkcs11.CKO_PRIVATE_KEY),
	}

	if err := ctx.FindObjectsInit(session, privKeyTemplate); err != nil {
		return nil, nil, fmt.Errorf("find private key init: %w", err)
	}

	objs, _, err := ctx.FindObjects(session, 1)
	ctx.FindObjectsFinal(session)
	if err != nil || len(objs) == 0 {
		return nil, nil, fmt.Errorf("no private key found on slot %d", slot)
	}

	privKey := objs[0]

	// Detect key type: RSA → CKM_RSA_PKCS with DigestInfo wrapper;
	// EC → CKM_ECDSA over the raw hash (no DigestInfo) per PRD §F5.11.
	keyTypeAttr, err := ctx.GetAttributeValue(session, privKey, []*pkcs11.Attribute{
		pkcs11.NewAttribute(pkcs11.CKA_KEY_TYPE, nil),
	})
	if err != nil || len(keyTypeAttr) == 0 || len(keyTypeAttr[0].Value) == 0 {
		return nil, nil, fmt.Errorf("could not read CKA_KEY_TYPE: %w", err)
	}
	keyType := uint(keyTypeAttr[0].Value[0])

	var mechanism []*pkcs11.Mechanism
	var dataToSign []byte
	switch keyType {
	case pkcs11.CKK_RSA:
		mechanism = []*pkcs11.Mechanism{pkcs11.NewMechanism(pkcs11.CKM_RSA_PKCS, nil)}
		// RSA PKCS#1 v1.5 expects DigestInfo(hash)
		dataToSign = append(sha256DigestInfoPrefix(), hashBytes...)
	case pkcs11.CKK_EC: // CKK_ECDSA is an alias for CKK_EC in the PKCS#11 spec
		// ECDSA signs the raw hash; the token returns r||s concatenation (PKCS#11 spec).
		// pyHanko's CMS layer expects this raw concatenation form too.
		mechanism = []*pkcs11.Mechanism{pkcs11.NewMechanism(pkcs11.CKM_ECDSA, nil)}
		dataToSign = hashBytes
	default:
		return nil, nil, fmt.Errorf("unsupported CKA_KEY_TYPE 0x%x — only RSA and ECDSA supported", keyType)
	}

	if err := ctx.SignInit(session, mechanism, privKey); err != nil {
		return nil, nil, fmt.Errorf("sign init: %w", err)
	}

	sig, err := ctx.Sign(session, dataToSign)
	if err != nil {
		return nil, nil, fmt.Errorf("sign: %w", err)
	}

	// Also get the cert DER for the response
	certTemplate := []*pkcs11.Attribute{
		pkcs11.NewAttribute(pkcs11.CKA_CLASS, pkcs11.CKO_CERTIFICATE),
	}
	ctx.FindObjectsInit(session, certTemplate)
	certObjs, _, _ := ctx.FindObjects(session, 1)
	ctx.FindObjectsFinal(session)

	var certDER []byte
	if len(certObjs) > 0 {
		attrs, err := ctx.GetAttributeValue(session, certObjs[0], []*pkcs11.Attribute{
			pkcs11.NewAttribute(pkcs11.CKA_VALUE, nil),
		})
		if err == nil && len(attrs) > 0 {
			certDER = attrs[0].Value
		}
	}

	return sig, certDER, nil
}

// Destroy cleans up all PKCS#11 contexts.
func (h *PKCS11Handler) Destroy() {
	h.mu.Lock()
	defer h.mu.Unlock()

	for path, ctx := range h.contexts {
		ctx.Finalize()
		ctx.Destroy()
		delete(h.contexts, path)
	}
}

// sha256DigestInfoPrefix returns the DER-encoded DigestInfo prefix for SHA-256.
// This is prepended to the hash before RSA PKCS#1 v1.5 signing.
func sha256DigestInfoPrefix() []byte {
	return []byte{
		0x30, 0x31, 0x30, 0x0d, 0x06, 0x09, 0x60, 0x86,
		0x48, 0x01, 0x65, 0x03, 0x04, 0x02, 0x01, 0x05,
		0x00, 0x04, 0x20,
	}
}

func parseKeyUsage(ku x509.KeyUsage) []string {
	var usages []string
	if ku&x509.KeyUsageDigitalSignature != 0 {
		usages = append(usages, "digitalSignature")
	}
	if ku&x509.KeyUsageContentCommitment != 0 {
		usages = append(usages, "nonRepudiation")
	}
	if ku&x509.KeyUsageKeyEncipherment != 0 {
		usages = append(usages, "keyEncipherment")
	}
	if ku&x509.KeyUsageDataEncipherment != 0 {
		usages = append(usages, "dataEncipherment")
	}
	if ku&x509.KeyUsageKeyAgreement != 0 {
		usages = append(usages, "keyAgreement")
	}
	if ku&x509.KeyUsageCertSign != 0 {
		usages = append(usages, "keyCertSign")
	}
	if ku&x509.KeyUsageCRLSign != 0 {
		usages = append(usages, "cRLSign")
	}
	return usages
}

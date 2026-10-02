package com.h4xtor.share;

import android.app.Activity;

import com.google.mlkit.vision.barcode.common.Barcode;
import com.google.mlkit.vision.codescanner.GmsBarcodeScanner;
import com.google.mlkit.vision.codescanner.GmsBarcodeScannerOptions;
import com.google.mlkit.vision.codescanner.GmsBarcodeScanning;

/**
 * QR scanning through Google's code scanner: no camera permission, no camera
 * code in this app, and the UI is provided by Google Play services.
 */
public final class QrScanner {
    public interface Result {
        void onScanned(String value);
        void onUnavailable(String reason);
    }

    private QrScanner() {
    }

    public static void scan(Activity activity, Result result) {
        try {
            GmsBarcodeScannerOptions options = new GmsBarcodeScannerOptions.Builder()
                    .setBarcodeFormats(Barcode.FORMAT_QR_CODE)
                    .build();
            GmsBarcodeScanner scanner = GmsBarcodeScanning.getClient(activity, options);
            scanner.startScan()
                    .addOnSuccessListener(barcode -> {
                        String value = barcode.getRawValue();
                        if (value != null) {
                            result.onScanned(value);
                        }
                    })
                    .addOnFailureListener(error -> result.onUnavailable(
                            "Kameraet kunne ikke scanne. Du kan i stedet scanne koden med telefonens "
                                    + "kamera-app, eller forbinde med en 6-cifret kode."));
        } catch (Throwable error) {
            result.onUnavailable("QR-scanneren kræver Google Play-tjenester. Scan koden med kamera-appen "
                    + "i stedet, eller forbind med en 6-cifret kode.");
        }
    }
}

package com.flashsale.inventory.dto;

import java.util.Map;

/**
 * Standardized error response.
 */
public record ErrorResponse(
        int status,
        String error,
        String message,
        Map<String, String> details
) {
    public ErrorResponse(int status, String error, String message) {
        this(status, error, message, null);
    }
}
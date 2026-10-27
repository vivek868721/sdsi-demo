package com.flashsale.inventory.model;

/**
 * Lifecycle states for a reservation.
 * Transitions are strictly enforced in the service layer.
 */
public enum ReservationStatus {
    PENDING,    // Reserved but not yet confirmed — stock held with TTL
    CONFIRMED,  // Reservation finalized — stock sold
    CANCELLED,  // User explicitly cancelled — stock restored
    EXPIRED     // TTL elapsed without confirmation — stock restored
}
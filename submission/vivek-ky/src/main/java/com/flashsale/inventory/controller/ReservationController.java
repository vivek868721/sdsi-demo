package com.flashsale.inventory.controller;

import com.flashsale.inventory.dto.ReservationResponse;
import com.flashsale.inventory.dto.ReserveRequest;
import com.flashsale.inventory.service.ReservationService;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.Parameter;
import io.swagger.v3.oas.annotations.media.Content;
import io.swagger.v3.oas.annotations.media.Schema;
import io.swagger.v3.oas.annotations.responses.ApiResponse;
import io.swagger.v3.oas.annotations.responses.ApiResponses;
import io.swagger.v3.oas.annotations.tags.Tag;
import jakarta.validation.Valid;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

/**
 * Reservation lifecycle endpoints.
 *
 * All mutating endpoints use per-SKU pessimistic row-level locking
 * to ensure correct behaviour under high concurrency.
 */
@RestController
@RequestMapping("/api/reservations")
@Tag(name = "Reservations", description = "Reserve, confirm, cancel flash-sale stock")
public class ReservationController {

    private final ReservationService reservationService;

    public ReservationController(ReservationService reservationService) {
        this.reservationService = reservationService;
    }

    @PostMapping
    @Operation(summary = "Reserve stock", description = "Atomically reserves stock for a user with TTL")
    @ApiResponses({
            @ApiResponse(responseCode = "201", description = "Reservation created"),
            @ApiResponse(responseCode = "404", description = "SKU not found", content = @Content),
            @ApiResponse(responseCode = "409", description = "Insufficient stock or quota exceeded", content = @Content)
    })
    public ResponseEntity<ReservationResponse> reserve(
            @Valid @RequestBody ReserveRequest request,
            @Parameter(description = "Client-supplied idempotency key to prevent duplicate deductions")
            @RequestHeader(value = "X-Idempotency-Key", required = false) String idempotencyKey) {
        ReservationResponse response = reservationService.reserve(
                request.sku(), request.userId(), request.quantity(), idempotencyKey);
        return ResponseEntity.status(HttpStatus.CREATED).body(response);
    }

    @PostMapping("/{reservationId}/confirm")
    @Operation(summary = "Confirm reservation", description = "Atomically transitions PENDING → CONFIRMED, moves stock to sold")
    @ApiResponses({
            @ApiResponse(responseCode = "200", description = "Reservation confirmed"),
            @ApiResponse(responseCode = "400", description = "Cannot confirm cancelled/expired reservation", content = @Content),
            @ApiResponse(responseCode = "404", description = "Reservation not found", content = @Content),
            @ApiResponse(responseCode = "410", description = "Reservation has expired", content = @Content)
    })
    public ReservationResponse confirm(@PathVariable String reservationId) {
        return reservationService.confirm(reservationId);
    }

    @PostMapping("/{reservationId}/cancel")
    @Operation(summary = "Cancel reservation", description = "Atomically transitions PENDING → CANCELLED, restores stock to available")
    @ApiResponses({
            @ApiResponse(responseCode = "200", description = "Reservation cancelled"),
            @ApiResponse(responseCode = "400", description = "Cannot cancel confirmed/expired reservation", content = @Content),
            @ApiResponse(responseCode = "404", description = "Reservation not found", content = @Content)
    })
    public ReservationResponse cancel(@PathVariable String reservationId) {
        return reservationService.cancel(reservationId);
    }

    @GetMapping("/{reservationId}")
    @Operation(summary = "Get reservation", description = "Returns the current state of a reservation")
    public ReservationResponse getReservation(@PathVariable String reservationId) {
        return reservationService.getByReservationId(reservationId);
    }
}
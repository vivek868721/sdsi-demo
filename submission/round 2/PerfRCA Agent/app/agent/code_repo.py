"""
Code Repository & Commit Inspection Engine for PerfRCA Agent.
Maintains AST representations, commit history (commit b8f3a9e), source files, and fix generation.
"""

from typing import Dict, Any

ORIGINAL_ORDER_SERVICE_JAVA = '''package com.enterprise.order.service;

import com.enterprise.order.dto.OrderDTO;
import com.enterprise.order.repository.OrderRepository;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import javax.sql.DataSource;
import java.sql.Connection;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.SQLException;

@Service
public class OrderService {
    private static final Logger log = LoggerFactory.getLogger(OrderService.class);

    private final DataSource dataSource;
    private final OrderRepository orderRepository;

    public OrderService(DataSource dataSource, OrderRepository orderRepository) {
        this.dataSource = dataSource;
        this.orderRepository = orderRepository;
    }

    @Transactional(readOnly = true)
    public OrderDTO getOrderById(String orderId) {
        return orderRepository.findById(orderId)
                .map(this::mapToDTO)
                .orElse(null);
    }
}
'''

REGRESSED_ORDER_SERVICE_JAVA = '''package com.enterprise.order.service;

import com.enterprise.order.dto.OrderDTO;
import com.enterprise.order.repository.OrderRepository;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import javax.sql.DataSource;
import java.sql.Connection;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.SQLException;

@Service
public class OrderService {
    private static final Logger log = LoggerFactory.getLogger(OrderService.class);

    private final DataSource dataSource;
    private final OrderRepository orderRepository;

    public OrderService(DataSource dataSource, OrderRepository orderRepository) {
        this.dataSource = dataSource;
        this.orderRepository = orderRepository;
    }

    @Transactional(readOnly = true)
    public OrderDTO getOrderById(String orderId) {
        return orderRepository.findById(orderId)
                .map(this::mapToDTO)
                .orElse(null);
    }

    /**
     * Introduced in commit b8f3a9e by dev-intern:
     * Fast-path lookup bypassing Spring Data JPA reflection overhead.
     * BUG: Leaks JDBC Connection, PreparedStatement and ResultSet!
     */
    public OrderDTO getOrderDetailsFast(String orderId) throws SQLException {
        // [DEFECT: MISSING RESOURCE CLEANUP]
        Connection conn = dataSource.getConnection(); 
        PreparedStatement stmt = conn.prepareStatement(
            "SELECT id, user_id, amount, status, created_at FROM orders WHERE id = ?"
        );
        stmt.setString(1, orderId);
        ResultSet rs = stmt.executeQuery();

        if (rs.next()) {
            return new OrderDTO(
                rs.getString("id"),
                rs.getString("user_id"),
                rs.getBigDecimal("amount"),
                rs.getString("status"),
                rs.getTimestamp("created_at").toInstant()
            );
        }
        return null;
        // FATAL: conn, stmt, and rs are NEVER closed or returned to HikariCP pool!
    }

    private OrderDTO mapToDTO(Object entity) {
        // Mapping implementation
        return null;
    }
}
'''

FIXED_ORDER_SERVICE_JAVA = '''package com.enterprise.order.service;

import com.enterprise.order.dto.OrderDTO;
import com.enterprise.order.repository.OrderRepository;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import javax.sql.DataSource;
import java.sql.Connection;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.SQLException;

@Service
public class OrderService {
    private static final Logger log = LoggerFactory.getLogger(OrderService.class);

    private final DataSource dataSource;
    private final OrderRepository orderRepository;

    public OrderService(DataSource dataSource, OrderRepository orderRepository) {
        this.dataSource = dataSource;
        this.orderRepository = orderRepository;
    }

    @Transactional(readOnly = true)
    public OrderDTO getOrderById(String orderId) {
        return orderRepository.findById(orderId)
                .map(this::mapToDTO)
                .orElse(null);
    }

    /**
     * Fast-path lookup bypassing Spring Data JPA reflection overhead.
     * VERIFIED FIX: Uses Java try-with-resources to guarantee connection return to HikariCP.
     */
    public OrderDTO getOrderDetailsFast(String orderId) throws SQLException {
        String sql = "SELECT id, user_id, amount, status, created_at FROM orders WHERE id = ?";
        
        try (Connection conn = dataSource.getConnection();
             PreparedStatement stmt = conn.prepareStatement(sql)) {
            
            stmt.setString(1, orderId);
            
            try (ResultSet rs = stmt.executeQuery()) {
                if (rs.next()) {
                    return new OrderDTO(
                        rs.getString("id"),
                        rs.getString("user_id"),
                        rs.getBigDecimal("amount"),
                        rs.getString("status"),
                        rs.getTimestamp("created_at").toInstant()
                    );
                }
                return null;
            }
        }
    }

    private OrderDTO mapToDTO(Object entity) {
        // Mapping implementation
        return null;
    }
}
'''

COMMIT_B8F3A9E = {
    "commit_hash": "b8f3a9e917d23a6c9812df93f0b47120a4b3d115",
    "short_hash": "b8f3a9e",
    "author": "Alex Dev <alex.dev@acme-commerce.com>",
    "date": "2026-10-27 10:14:22 +0530",
    "message": "perf(order): bypass ORM reflection with direct JDBC fast-path lookup",
    "file_path": "src/main/java/com/enterprise/order/service/OrderService.java",
    "lines_added": 24,
    "lines_removed": 0,
    "defect_type": "RESOURCE_LEAK_UNCLOSED_CONNECTION",
    "defect_description": (
        "Method getOrderDetailsFast acquires java.sql.Connection from HikariDataSource without a "
        "try-with-resources statement or finally block. Every invocation permanently retains 1 leased connection."
    )
}

DIFF_UNIFIED = """--- a/src/main/java/com/enterprise/order/service/OrderService.java
+++ b/src/main/java/com/enterprise/order/service/OrderService.java
@@ -33,18 +33,23 @@ public class OrderService {
     /**
      * Fast-path lookup bypassing Spring Data JPA reflection overhead.
+     * VERIFIED FIX: Uses Java try-with-resources to guarantee connection return to HikariCP.
      */
     public OrderDTO getOrderDetailsFast(String orderId) throws SQLException {
-        Connection conn = dataSource.getConnection(); 
-        PreparedStatement stmt = conn.prepareStatement(
-            "SELECT id, user_id, amount, status, created_at FROM orders WHERE id = ?"
-        );
-        stmt.setString(1, orderId);
-        ResultSet rs = stmt.executeQuery();
-
-        if (rs.next()) {
-            return new OrderDTO(
-                rs.getString("id"),
-                rs.getString("user_id"),
-                rs.getBigDecimal("amount"),
-                rs.getString("status"),
-                rs.getTimestamp("created_at").toInstant()
-            );
-        }
-        return null;
+        String sql = "SELECT id, user_id, amount, status, created_at FROM orders WHERE id = ?";
+        
+        try (Connection conn = dataSource.getConnection();
+             PreparedStatement stmt = conn.prepareStatement(sql)) {
+            
+            stmt.setString(1, orderId);
+            
+            try (ResultSet rs = stmt.executeQuery()) {
+                if (rs.next()) {
+                    return new OrderDTO(
+                        rs.getString("id"),
+                        rs.getString("user_id"),
+                        rs.getBigDecimal("amount"),
+                        rs.getString("status"),
+                        rs.getTimestamp("created_at").toInstant()
+                    );
+                }
+                return null;
+            }
+        }
     }
"""

class CodeRepoEngine:
    """Manages repository inspection, blame analysis, and patch synthesis."""

    @staticmethod
    def get_commit_b8f3a9e() -> Dict[str, Any]:
        return COMMIT_B8F3A9E

    @staticmethod
    def get_regressed_code() -> str:
        return REGRESSED_ORDER_SERVICE_JAVA

    @staticmethod
    def get_fixed_code() -> str:
        return FIXED_ORDER_SERVICE_JAVA

    @staticmethod
    def get_unified_diff() -> str:
        return DIFF_UNIFIED

    @staticmethod
    def generate_jira_ticket() -> Dict[str, Any]:
        return {
            "ticket_id": "PERF-512",
            "title": "[P0 Blocker] Database Connection Pool Starvation in OrderService.getOrderDetailsFast()",
            "priority": "P0 - Blocker",
            "type": "Defect / Incident Remediation",
            "assignee": "PerfRCA Autonomous Agent",
            "reporter": "PerfRCA Watchdog Bot",
            "components": ["Database / Connection Pool", "Order Service", "HikariCP"],
            "matched_historical_incident": "OPP-3716",
            "suspect_commit": "b8f3a9e (author: Alex Dev)",
            "affected_file": "src/main/java/com/enterprise/order/service/OrderService.java",
            "impact_summary": (
                "HikariCP connection pool saturated at 10/10 active connections. DB P99 latency degraded from "
                "15ms to >3000ms. DB Throughput collapsed from 45 TPS to ~1.8 TPS. Over 45,000 connection timeout errors logged."
            ),
            "root_cause_analysis": (
                "Commit b8f3a9e introduced a high-traffic fast-path lookup method `getOrderDetailsFast` that acquires "
                "a raw JDBC `java.sql.Connection` from HikariDataSource without scoping it within Java 7+ "
                "`try-with-resources`. Leased connections were never closed or returned to the pool, exhausting all 10 pool slots within seconds."
            ),
            "remediation_status": "PATCH_VERIFIED_AND_GENERATED",
            "pull_request_branch": "fix/PERF-512-order-service-try-with-resources",
            "automated_test_command": "mvn test -Dtest=OrderServicePoolExhaustionTest"
        }

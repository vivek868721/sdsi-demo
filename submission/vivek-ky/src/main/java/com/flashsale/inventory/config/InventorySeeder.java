package com.flashsale.inventory.config;

import com.flashsale.inventory.model.Product;
import com.flashsale.inventory.repository.ProductRepository;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.CommandLineRunner;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.core.io.ClassPathResource;

import java.io.InputStream;
import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.List;

/**
 * Seeds the database with products from inventory.json on startup.
 * Uses insert-or-skip logic so repeated restarts are safe.
 */
@Configuration
public class InventorySeeder {

    private static final Logger log = LoggerFactory.getLogger(InventorySeeder.class);

    @Bean
    CommandLineRunner seedInventory(ProductRepository productRepository, ObjectMapper objectMapper) {
        return args -> {
            if (productRepository.count() > 0) {
                log.info("Inventory already seeded — {} products found. Skipping seed.", productRepository.count());
                return;
            }

            try (InputStream in = new ClassPathResource("inventory.json").getInputStream()) {
                JsonNode root = objectMapper.readTree(in);
                JsonNode productsNode = root.get("products");

                List<Product> products = new ArrayList<>();
                for (JsonNode node : productsNode) {
                    Product p = new Product();
                    p.setSku(node.get("sku").asText());
                    p.setName(node.get("name").asText());
                    p.setTotalStock(node.get("total_stock").asInt());
                    p.setAvailableStock(node.get("total_stock").asInt()); // all available initially
                    p.setReservedStock(0);
                    p.setSoldStock(0);
                    p.setMaxPerUser(node.get("max_per_user").asInt());
                    p.setPrice(BigDecimal.valueOf(node.get("price").asDouble()));
                    products.add(p);
                }

                productRepository.saveAll(products);
                log.info("Seeded {} products from inventory.json", products.size());
            } catch (Exception e) {
                log.error("Failed to seed inventory: {}", e.getMessage(), e);
                throw new RuntimeException("Inventory seeding failed", e);
            }
        };
    }
}
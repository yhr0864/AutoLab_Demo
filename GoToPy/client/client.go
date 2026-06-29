package main

import (
	"context"
	"log"
	"time"

	pb "GoToPy/client/proto/calculator"

	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials/insecure"
)

func main() {
	// Connect to the Python gRPC server
	conn, err := grpc.NewClient("localhost:50051", grpc.WithTransportCredentials(insecure.NewCredentials()))
	if err != nil {
		log.Fatalf("Failed to connect: %v", err)
	}
	defer conn.Close()

	client := pb.NewCalculatorClient(conn)

	// Numbers to add
	a := 235.99
	b := 23.567

	ctx, cancel := context.WithTimeout(context.Background(), time.Second)
	defer cancel()

	// Call the Add RPC
	resp, err := client.Add(ctx, &pb.AddRequest{A: a, B: b})
	if err != nil {
		log.Fatalf("Add RPC failed: %v", err)
	}

	log.Printf("Result: %.2f + %.2f = %.2f\n", a, b, resp.GetResult())
}

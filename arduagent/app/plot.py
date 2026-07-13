import matplotlib.pyplot as plt


class Plot:
    def plot_search_pattern(self, area, pattern, filename="search_pattern.png"):
        # Extract area coordinates
        area_y, area_x = zip(*area)

        # Extract pattern coordinates
        pattern_x, pattern_y = zip(
            *[(lon, lat) for lat, lon, _ in pattern], strict=False
        )

        # Create plot
        plt.figure(figsize=(8, 8))
        plt.plot(area_x, area_y, "b-", label="Area")  # Plot area in blue
        plt.plot(
            pattern_x, pattern_y, "ro-", label="Search Pattern"
        )  # Plot pattern in red
        plt.fill(
            area_x, area_y, color="blue", alpha=0.1
        )  # Fill area with light blue color
        plt.title(filename)
        plt.xlabel("Longitude")
        plt.ylabel("Latitude")
        plt.legend()
        plt.grid(True)
        plt.axis("equal")

        # Save plot to file
        plt.savefig(filename)
        plt.close()

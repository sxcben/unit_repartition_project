# 🏠 Unit Repartition Project

This project creates a small **website** where people can trade or swap rooms (or any shared objects) — a bit like an **auction**, but with rules that keep the total price fixed and everyone treated fairly.

---

## Why I Made It

When I moved into an apartment with friends, we had one total rent but no price per room.  
To make it fair, I built this app so we could negotiate and find prices that make everyone happy.

Each person can mark if they’re satisfied, propose swaps, or accept offers — all while keeping the total rent constant.

---

## � How to run

1. Run the Python file in your terminal:
   ```bash
   python roomswap.py
   ```

2. Enter the **password** from this website:  
    [https://loca.lt/mytunnelpassword](https://loca.lt/mytunnelpassword)

   The one who runs it becomes the **host** (it creates the public link for others).

3. Then open the link shown in your terminal (something like `http://localhost:8000`) and everyone can join!

---

## How It Works

- The total rent stays fixed for the apartment.
- Each person starts with a random room and price=total/nber_rooms.
- You can make swap offers or accept others’ offers.
- When asking for someone to change room, let say you have room 1 foor 900 and his is 950 but you want his and you are willing to pay 970. This means you will propose yours for 880 (to keep same total). If he accepts the rooms are swapped, and if he doesn't then you keep the rooms but the price change: now he pays 970 and you pay 880 (because since nobody really owns nothing and you are willing to pay 970 then he has to pay the price at least if he wants to keep it).

---

Fun to use with friends and a good way to learn how auction‑like systems can work in real life 😄

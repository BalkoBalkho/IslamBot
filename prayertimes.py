import asyncio
import discord
import pytz
from time import sleep
from aiomysql.sa import create_engine
from sqlalchemy import create_engine
from aiohttp import ClientSession
from datetime import datetime
from dbhandler import PrayerTimesHandler, user, password, host, database, user_prayer_times_table_name, server_prayer_times_table_name
from discord.ext import commands, tasks
from discord.ext.commands import CheckFailure, MissingRequiredArgument, BadArgument
from pytz import timezone

icon = 'https://www.muslimpro.com/img/muslimpro-logo-2016-250.png'

headers = {'content-type': 'application/json'}


class PrayerTimes(commands.Cog):

    def __init__(self, bot):
        self.session = ClientSession(loop = bot.loop)
        self.bot = bot
        self.update_times.start()
        self.methods_url = 'https://api.aladhan.com/methods'
        self.prayertimes_url = 'http://api.aladhan.com/timingsByAddress?address={}&method={}&school={}'
        self.check_times.start()
        self.save_dataframes.start()

    async def get_calculation_methods(self):
        async with self.session.get(self.methods_url, headers=headers) as resp:
            data = await resp.json()
            data = data['data'].values()

            # There's an entry ('CUSTOM') with no 'name' value, so we need to ignore it:
            calculation_methods = {method['id']: method['name'] for method in data if int(method['id']) != 99}
            return calculation_methods

    async def get_prayertimes(self, location, calculation_method):
        url = self.prayertimes_url.format(location, calculation_method, '0')

        async with self.session.get(url, headers=headers) as resp:
            data = await resp.json()
            fajr = data['data']['timings']['Fajr']
            sunrise = data['data']['timings']['Sunrise']
            dhuhr = data['data']['timings']['Dhuhr']
            asr = data['data']['timings']['Asr']
            maghrib = data['data']['timings']['Maghrib']
            isha = data['data']['timings']['Isha']
            imsak = data['data']['timings']['Imsak']
            midnight = data['data']['timings']['Midnight']
            date = data['data']['date']['readable']

        url = self.prayertimes_url.format(location, calculation_method, '1')

        async with self.session.get(url, headers=headers) as resp:
            data = await resp.json()
            hanafi_asr = data['data']['timings']['Asr']

        return fajr, sunrise, dhuhr, asr, hanafi_asr, maghrib, isha, imsak, midnight, date

    @commands.command(name="prayertimes")
    async def prayertimes(self, ctx, *, location):

        calculation_method = await PrayerTimesHandler.get_user_calculation_method(ctx.author.id)
        calculation_method = int(calculation_method)

        try:
            fajr, sunrise, dhuhr, asr, hanafi_asr, maghrib, isha, imsak, midnight, date = await \
                self.get_prayertimes(location, calculation_method)
        except:
            return await ctx.send("**Location not found**.")

        em = discord.Embed(colour=0x2186d3, title=date)
        em.set_author(name=f'Prayer Times for {location.title()}', icon_url=icon)
        em.add_field(name=f'**Imsak (إِمْسَاك)**', value=f'{imsak}', inline=True)
        em.add_field(name=f'**Fajr (صلاة الفجر)**', value=f'{fajr}', inline=True)
        em.add_field(name=f'**Sunrise (طلوع الشمس)**', value=f'{sunrise}', inline=True)
        em.add_field(name=f'**Ẓuhr (صلاة الظهر)**', value=f'{dhuhr}', inline=True)
        em.add_field(name=f'**Asr (صلاة العصر)**', value=f'{asr}', inline=True)
        em.add_field(name=f'**Asr - Ḥanafī School (صلاة العصر - حنفي)**', value=f'{hanafi_asr}', inline=True)
        em.add_field(name=f'**Maghrib (صلاة المغرب)**', value=f'{maghrib}', inline=True)
        em.add_field(name=f'**Isha (صلاة العشاء)**', value=f'{isha}', inline=True)
        em.add_field(name=f'**Midnight (منتصف الليل)**', value=f'{midnight}', inline=True)

        method_names = await self.get_calculation_methods()
        em.set_footer(text=f'Calculation Method: {method_names[calculation_method]}')
        await ctx.send(embed=em)

    @prayertimes.error
    async def on_prayertimes_error(self, ctx, error):
        if isinstance(error, MissingRequiredArgument):
            await ctx.send(f"**Please provide a location**. \n\nExample: `{ctx.prefix}prayertimes Dubai, UAE`")

    @commands.command(name="setcalculationmethod")
    async def setcalculationmethod(self, ctx):

        def is_user(msg):
            return msg.author == ctx.author

        em = discord.Embed(colour=0x467f05, description="Please select a **calculation method number**.\n\n")
        em.set_author(name='Calculation Methods', icon_url=icon)
        calculation_methods = await self.get_calculation_methods()
        for method, name in calculation_methods.items():
            em.description = f'{em.description}**{method}** - {name}\n'
        await ctx.send(embed=em)

        try:
            message = await self.bot.wait_for('message', timeout=120.0, check=is_user)
            method = message.content
            try:
                method = int(method)
                if method not in calculation_methods.keys():
                    raise TypeError
            except:
                return await ctx.send("❌ **Invalid calculation method number.** ")

            await PrayerTimesHandler.update_user_calculation_method(ctx.author.id, method)
            await ctx.send(':white_check_mark: **Successfully updated!**')

        except asyncio.TimeoutError:
            await ctx.send("❌ **Timed out**. Please try again.")

    @commands.command(name="addprayerreminder")
    async def addprayerreminder(self, ctx):

        def is_user(msg):
            return msg.author == ctx.author

        em = discord.Embed(colour=0x467f05, title='Prayer Times Reminder Setup')
        em.set_author(name=ctx.guild, icon_url=icon)

        try:
            # Ask whether we want to send personal reminders (DMs) or public reminders (in a channel).
            em.description = "Do you want to receive reminders through your **server**, or **DMs**?" \
                             "\n\n__**Please type either `server` or `DMs`.**__" \
                             "\n\nYou __must__ have the **🔒 Administrator** permission to create server reminders." \
                             "\n\nYou __must__ share a mutual server with the bot and allow it to send you DMs to " \
                             "receive DM reminders."
            help_msg = await ctx.send(embed=em)

            message = await self.bot.wait_for('message', timeout=60.0, check=is_user)
            if message.content.lower() == 'server':
                server = True
            elif message.content.lower() == 'dms':
                server = False
            else:
                return await ctx.send("❌ **Invalid response**. Aborting.")

            # Ask for a reminder channel for server reminders.
            if server is True:
                em.description = "Please mention the **channel** to send prayer time reminders in."
                await help_msg.edit(embed=em)

                message = await self.bot.wait_for('message', timeout=60.0, check=is_user)
                if message.channel_mentions:
                    channel = message.channel_mentions[0]
                    if ctx.author.guild_permissions.administrator:
                        channel_id = channel.id
                    else:
                        return await ctx.send("❌ **You do not have the Administrator permission**. Aborting.")
                else:
                    return await ctx.send("❌ **Invalid channel**. Aborting.")
            # Ask for location.
            em.description = "Please set the **location** to send prayer times for. " \
                             "\n\n**Example**: Burj Khalifa, Dubai, UAE"
            await help_msg.edit(embed=em)

            message = await self.bot.wait_for('message', timeout=60.0, check=is_user)
            location = message.content

            # Ask for timezone.
            em.description = "Please select the **__timezone__ of the location**. " \
                             "**[Click here](https://timezonedb.com/time-zones)** for a list of timezones." \
                             "\n\n**Examples**: `Asia/Dubai`, `Europe/London`, `America/Toronto`"
            await help_msg.edit(embed=em)

            message = await self.bot.wait_for('message', timeout=180.0, check=is_user)
            if message.content in pytz.all_timezones:
                timezone = message.content
            else:
                return await ctx.send("❌ **Invalid timezone**. Aborting.")

            # Ask for calculation method.
            em.description = "Please select the prayer times **calculation method number**.\n\n"
            calculation_methods = await self.get_calculation_methods()
            for method, name in calculation_methods.items():
                em.description = f'{em.description}**{method}** - {name}\n'
            await help_msg.edit(embed=em)

            message = await self.bot.wait_for('message', timeout=180.0, check=is_user)
            method = message.content
            try:
                method = int(method)
                if method not in calculation_methods.keys():
                    raise TypeError
            except TypeError:
                return await ctx.send("❌ **Invalid calculation method number.** ")

            # Update database.
            if server is True:
                await PrayerTimesHandler.update_server_prayer_times_details(ctx.guild.id, channel_id, location, timezone, method)
            else:
                await PrayerTimesHandler.update_user_prayer_times_details(ctx.author.id, location, timezone, method)

            # Send success message.
            em.description = f":white_check_mark: **Setup complete!**" \
                             f"\n\n**Location**: {location}\n**Timezone**: {timezone}" \
                             f"\n**Calculation Method**: {method}" \
                             f"\n\nIf you would like to change these details, use `{ctx.prefix}removeprayerreminder` " \
                             f"or `{ctx.prefix}removepersonalprayerreminder` and run this command again."
            await help_msg.edit(embed=em)

        except asyncio.TimeoutError:
            await ctx.send("**Timed out.** Please try again.")

    @commands.command(name="removeprayerreminder")
    @commands.has_permissions(administrator=True)
    async def removeprayerreminder(self, ctx, channel: discord.TextChannel):
        try:
            await PrayerTimesHandler.delete_server_prayer_times_details(channel.id)
            await ctx.send(f":white_check_mark: **You will no longer receive prayer times reminders in <#{channel.id}>.**")
        except:
            await ctx.send("❌ **An error occurred**.")

    @commands.command(name="removepersonalprayerreminder")
    async def removepersonalprayerreminder(self, ctx):

        await PrayerTimesHandler.delete_user_prayer_times_details(ctx.author.id)
        await ctx.send(f":white_check_mark: **You will no longer receive prayer times reminders.**")

    @addprayerreminder.error
    @removeprayerreminder.error
    async def on_error(self, ctx, error):
        if isinstance(error, CheckFailure):
            await ctx.send("🔒 You need the **Administrator** permission to use this command.")
        if isinstance(error, MissingRequiredArgument) or isinstance(error, BadArgument):
            await ctx.send("❌ **Please mention the channel to delete prayer time reminders for**.")

    @tasks.loop(hours=1)
    async def update_times(self):

        index = -1
        for location, method in zip(PrayerTimesHandler.server_df['location'], PrayerTimesHandler.server_df['calculation_method']):
            index = index + 1

            try:
                fajr, sunrise, dhuhr, asr, hanafi_asr, maghrib, isha, imsak, midnight, date = await self.get_prayertimes(location, int(method))

                PrayerTimesHandler.server_df.at[index, 'Fajr'] = fajr
                PrayerTimesHandler.server_df.at[index, 'Dhuhr'] = dhuhr
                PrayerTimesHandler.server_df.at[index, 'Asr'] = asr
                PrayerTimesHandler.server_df.at[index, 'Asr (Hanafi)'] = hanafi_asr
                PrayerTimesHandler.server_df.at[index, 'Maghrib'] = maghrib
                PrayerTimesHandler.server_df.at[index, 'Isha'] = isha

            except:
                PrayerTimesHandler.server_df.drop(index)
                print(f"Dropped {location} (index: {index}) due to error!")

            sleep(30/100)  # Respect API rate limit (which is 250 requests/30 seconds)

        index = -1
        for location, method in zip(PrayerTimesHandler.user_df['location'], PrayerTimesHandler.user_df['calculation_method']):
            index = index + 1

            try:
                fajr, sunrise, dhuhr, asr, hanafi_asr, maghrib, isha, imsak, midnight, date = await self.get_prayertimes(location, int(method))

                PrayerTimesHandler.user_df.at[index, 'Fajr'] = fajr
                PrayerTimesHandler.user_df.at[index, 'Dhuhr'] = dhuhr
                PrayerTimesHandler.user_df.at[index, 'Asr'] = asr
                PrayerTimesHandler.user_df.at[index, 'Asr (Hanafi)'] = hanafi_asr
                PrayerTimesHandler.user_df.at[index, 'Maghrib'] = maghrib
                PrayerTimesHandler.user_df.at[index, 'Isha'] = isha

            except:
                PrayerTimesHandler.user_df.drop(index)
                print(f"Dropped {location} (index: {index}) due to error!")

            sleep(30/100)  # Respect API rate limit (which is 250 requests/30 seconds).

    @update_times.before_loop
    async def before_update(self):
        await self.bot.wait_until_ready()

    @update_times.after_loop
    async def restart_update(self):
        print("Prayer time update failed, restarting.")
        await self.update_times.start()
        
    @tasks.loop(minutes=1)
    async def check_times(self):
        for row in PrayerTimesHandler.user_df.iterrows():
            data = row[1].to_dict()
            try:
                await self.evaluate_times(data, is_user = True)
            except Exception as e:
                print(f'USER ERROR! Error = {e}, Data = {data}')

        for row in PrayerTimesHandler.server_df.iterrows():
            data = row[1].to_dict()
            try:
                await self.evaluate_times(data, is_user = False)
            except Exception as e:
                print(f'SERVER ERROR! Error = {e}, Data = {data}')

    @check_times.before_loop
    async def before_checks(self):
        await self.bot.wait_until_ready()

    @check_times.after_loop
    async def restart_checks(self):
        await self.check_times.start()

    async def evaluate_times(self, data, is_user: bool):

        em = discord.Embed(colour=0x467f05)
        em.set_author(name='Prayer Times Reminder', icon_url=icon)

        if is_user:
            channel, location, time_zone, calculation_method, fajr, dhuhr, asr, asr_hanafi, maghrib, isha = \
                self.bot.get_user(int(data['user'])), data['location'], data['timezone'], data['calculation_method'], \
                data['Fajr'], data['Dhuhr'], data['Asr'], data['Asr (Hanafi)'], data['Maghrib'], data['Isha']

        else:
            channel, location, time_zone, calculation_method, fajr, dhuhr, asr, asr_hanafi, maghrib, isha = \
                self.bot.get_channel(int(data['channel'])), data['location'], data['timezone'], data['calculation_method'], data['Fajr'], \
                data['Dhuhr'], data['Asr'], data['Asr (Hanafi)'], data['Maghrib'], data['Isha']

        em.title = location

        tz = timezone(time_zone)
        tz_time = datetime.now(tz).strftime('%H:%M')

        success = False

        if tz_time == fajr:
            em.description = f"It is **Fajr** time in **{location}**! (__{fajr}__)" \
                             f"\n\n**Dhuhr** will be at __{dhuhr}__."
            success = True

        elif tz_time == dhuhr:
            em.description = f"It is **Dhuhr** time in **{location}**! (__{dhuhr}__)" \
                             f"\n\n**Asr** will be at __{asr}__."
            success = True

        elif tz_time == asr:
            em.description = f"It is **Asr** time in **{location}**! (__{asr}__)." \
                             f"\n\nFor Hanafis, Asr will be at __{asr_hanafi}__." \
                             f"\n\n**Maghrib** will be at __{maghrib}__."
            success = True

        elif tz_time == maghrib:
            em.description = f"It is **Maghrib** time in **{location}**! (__{maghrib}__)" \
                             f"\n\n**Isha** will be at __{isha}__."
            success = True

        elif tz_time == isha:
            em.description = f"It is **Isha** time in **{location}**! (__{isha}__)"
            success = True

        if success:
            await channel.send(embed=em)

    @tasks.loop(minutes=5)
    async def save_dataframes(self):

        engine = create_engine(f'mysql+pymysql://{user}:{password}@{host}:3306/{database}')
        connection = engine.connect()

        user_df_truncated = PrayerTimesHandler.user_df[['user', 'location', 'timezone', 'calculation_method']].copy()
        user_df_truncated.to_sql(f"{user_prayer_times_table_name}", engine, if_exists="replace", index=False)

        server_df_truncated = PrayerTimesHandler.server_df[['server', 'channel', 'location', 'timezone', 'calculation_method']].copy()
        server_df_truncated.to_sql(f"{server_prayer_times_table_name}", engine, if_exists="replace", index=False)

        connection.close()


def setup(bot):
    bot.add_cog(PrayerTimes(bot))
